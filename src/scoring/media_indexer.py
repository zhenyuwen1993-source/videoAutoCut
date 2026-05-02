"""Index every photo + video under a root directory using CLIP.

For each file:
- video: extract 3 sample frames (25%, 50%, 75% of duration)
- image: open directly
- compute CLIP image embedding
- score against a prompt bank → top-N tags
- save metadata + tags to a single JSON index

Output: data/media_index.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import torch
import open_clip
from PIL import Image

ROOT = Path(r"D:\gogogo video")
OUT = Path(r"D:\claudeWork\videoAutoCut\data\media_index.json")
PROGRESS = Path(r"D:\claudeWork\videoAutoCut\data\media_index.progress.json")
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

# Prompt bank: English query for CLIP -> Chinese display tag.
PROMPTS: list[tuple[str, str, str]] = [
    # (category, english prompt, chinese tag)
    ("scenery",      "a beautiful natural landscape, mountains and sky",  "风景"),
    ("scenery",      "a stunning waterfall with mist and water",          "瀑布"),
    ("scenery",      "an ocean beach with waves and sand",                "海滩"),
    ("scenery",      "a forest or park with green trees",                 "森林公园"),
    ("scenery",      "a desert canyon or rocky landscape",                "峡谷岩石"),
    ("scenery",      "a sunset or sunrise with colorful sky",             "日出日落"),
    ("scenery",      "a snowy mountain or winter landscape",              "雪山"),
    ("scenery",      "a lake or river reflection",                        "湖泊河流"),

    ("city",         "a modern city skyline with buildings",              "城市天际线"),
    ("city",         "a busy street scene with people and shops",         "街景"),
    ("city",         "an old town with historic architecture",            "老城区"),
    ("city",         "a famous landmark or monument",                     "地标建筑"),

    ("food",         "a plate of delicious food, restaurant meal",        "美食"),
    ("food",         "asian cuisine, ramen sushi or noodles",             "亚洲美食"),
    ("food",         "dessert or cake or sweet treats",                   "甜品"),
    ("food",         "drinks coffee tea or cocktails",                    "饮品"),

    ("people",       "a person posing for a portrait",                    "人物肖像"),
    ("people",       "a selfie of a smiling person",                      "自拍"),
    ("people",       "a group of friends or family",                      "合影"),
    ("people",       "people walking or activities",                      "人群"),

    ("indoor",       "the interior of a building or room",                "室内"),
    ("indoor",       "a museum or art gallery exhibit",                   "博物馆"),
    ("indoor",       "a hotel room or accommodation",                     "酒店"),
    ("indoor",       "a shopping mall or store",                          "商场"),

    ("transport",    "a car driving on a road",                           "开车"),
    ("transport",    "an airplane or airport",                            "飞机机场"),
    ("transport",    "a boat or ship on water",                           "船只"),
    ("transport",    "a train or train station",                          "火车"),

    ("night",        "city at night with lights and neon",                "夜景"),
    ("night",        "fireworks or a light show",                         "烟花灯光"),

    ("animals",      "a wild animal in nature",                           "野生动物"),
    ("animals",      "a pet dog or cat",                                  "宠物"),
    ("animals",      "birds or marine life",                              "鸟类海洋生物"),

    ("activity",     "people playing sports",                             "运动"),
    ("activity",     "swimming or beach activity",                        "游泳海滩活动"),
    ("activity",     "concert or live performance",                       "演出"),
    ("activity",     "shopping or browsing items",                        "购物"),

    ("misc",         "a blurry or unclear image",                         "模糊"),
    ("misc",         "a dark or underexposed image",                      "过暗"),
    ("misc",         "a screenshot or document",                          "截图"),
]


@dataclass
class FileEntry:
    path: str
    rel_path: str
    trip: str            # top-level folder
    kind: str            # "video" | "image"
    size_mb: float
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None  # videos only
    mtime: str = ""
    tags: list[dict] = field(default_factory=list)  # [{tag,en,score,category}]
    error: str | None = None


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # skip dirs in-place
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


def extract_frames(path: Path, duration: float, n: int = 3) -> list[Image.Image]:
    """Extract n frames at evenly spaced times. Returns list of PIL Images."""
    if duration <= 0:
        return []
    timestamps = [duration * (i + 1) / (n + 1) for i in range(n)]
    frames = []
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
        # Downscale large images to 336 max edge for CLIP
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024))
        img.load()
        return img
    except Exception:
        return None


class CLIPScorer:
    def __init__(self, device: str = "cuda"):
        print(f"Loading CLIP model on {device}...")
        self.device = device if torch.cuda.is_available() else "cpu"
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k", device=self.device,
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer("ViT-B-32")
        prompts = [p[1] for p in PROMPTS]
        with torch.no_grad():
            tokens = self.tokenizer(prompts).to(self.device)
            text_emb = self.model.encode_text(tokens)
            text_emb /= text_emb.norm(dim=-1, keepdim=True)
        self.text_emb = text_emb
        print(f"  loaded {len(prompts)} prompt embeddings")

    @torch.no_grad()
    def score_images(self, images: list[Image.Image], top_k: int = 5) -> list[dict]:
        if not images:
            return []
        batch = torch.stack([self.preprocess(im) for im in images]).to(self.device)
        emb = self.model.encode_image(batch)
        emb /= emb.norm(dim=-1, keepdim=True)
        # avg across frames for a video
        emb_avg = emb.mean(dim=0, keepdim=True)
        emb_avg /= emb_avg.norm(dim=-1, keepdim=True)
        sims = (emb_avg @ self.text_emb.T).squeeze(0)  # [n_prompts]
        top_vals, top_idx = sims.topk(top_k)
        return [
            {
                "category": PROMPTS[i.item()][0],
                "en": PROMPTS[i.item()][1],
                "tag": PROMPTS[i.item()][2],
                "score": round(float(s), 4),
            }
            for s, i in zip(top_vals.tolist(), top_idx.tolist())
            for s in [s]
        ]


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


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(iter_files(ROOT))
    print(f"Found {len(files)} media files under {ROOT}")

    scorer = CLIPScorer()
    done = load_progress()
    if OUT.exists() and done:
        existing: dict = json.loads(OUT.read_text(encoding="utf-8"))
        entries: dict[str, dict] = {e["path"]: e for e in existing.get("files", [])}
        print(f"Resuming: {len(done)} files already indexed.")
    else:
        entries = {}

    t0 = time.time()
    for i, path in enumerate(files):
        rel = path.relative_to(ROOT).as_posix()
        if str(path) in done:
            continue

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
                    frames = extract_frames(path, dur, n=3)
                    entry.tags = scorer.score_images(frames, top_k=5)
                else:
                    entry.error = "could not probe duration"
            else:
                img = load_image(path)
                if img:
                    entry.width, entry.height = img.size
                    entry.tags = scorer.score_images([img], top_k=5)
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
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(files) - (i + 1)) / rate if rate > 0 else 0
            top_tag = entry.tags[0]["tag"] if entry.tags else "?"
            print(
                f"[{i+1:>4}/{len(files)}] {rel[:60]:<60} "
                f"{kind:<5} top={top_tag} ({rate:.1f}/s, ETA {eta/60:.1f}min)"
            )

    print(f"\nDone. Index saved to {OUT}")


if __name__ == "__main__":
    main()
