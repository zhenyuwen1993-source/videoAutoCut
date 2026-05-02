"""Cut a Niagara Falls demo from MarchWen's selected US trip clips.

Manually curated cut list (this is the ground-truth hand-picked baseline
that the auto-scoring pipeline will eventually need to match or beat).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG = (
    r"C:\Users\zheny\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)
SOURCE_DIR = Path(r"D:\gogogo video\US trip\selected")
OUTPUT_DIR = Path(r"D:\claudeWork\videoAutoCut\output")
TEMP_DIR = OUTPUT_DIR / ".tmp_segments"


@dataclass
class Cut:
    file: str
    start: float
    duration: float
    note: str = ""


CUT_LIST: list[Cut] = [
    Cut("VID_20250721_090234_00_007.mp4",   0,    7,   "open: drive in"),
    Cut("VID_20250721_095610_00_012.mp4",  13,    7,   "walking the park"),
    Cut("VID_20250721_095610_00_012.mp4", 128,    8,   "falls overlook w/ tree"),
    Cut("VID_20250721_103653_00_022.mp4",  28,    7,   "dock: red ponchos"),
    Cut("VID_20250721_103259_00_021.mp4",   5,    7,   "boarding tunnel"),
    Cut("VID_20250721_103653_00_022.mp4", 148,    7,   "dock: dramatic clouds"),
    Cut("VID_20250721_104539_00_028.mp4",  56,    9,   "first approach: mist"),
    Cut("VID_20250721_105741_00_029.mp4",   0,  5.5,   "iconic wide w/ boat"),
    Cut("VID_20250721_104539_00_028.mp4", 446,    8,   "falls feature shot"),
    Cut("VID_20250721_104221_00_023.mp4",   0,  6.4,   "macro: foam + falls"),
    Cut("VID_20250721_104539_00_028.mp4", 547,    8,   "selfie smile (closer)"),
]


def normalize_segment(src: Path, start: float, duration: float, dst: Path) -> None:
    """Re-encode a segment to a uniform format so concat is seamless."""
    cmd = [
        FFMPEG,
        "-hide_banner", "-loglevel", "error", "-y",
        "-ss", str(start),
        "-i", str(src),
        "-t", str(duration),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-af", "afade=t=in:st=0:d=0.1,"
               f"afade=t=out:st={max(duration - 0.1, 0)}:d=0.1",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def concat_segments(segments: list[Path], output: Path) -> None:
    """Concat normalized segments via ffmpeg concat demuxer (lossless)."""
    list_file = TEMP_DIR / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{s.as_posix()}'" for s in segments),
        encoding="utf-8",
    )
    cmd = [
        FFMPEG,
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True)

    segments: list[Path] = []
    for i, cut in enumerate(CUT_LIST):
        src = SOURCE_DIR / cut.file
        dst = TEMP_DIR / f"{i:02d}_{cut.file}"
        print(f"[{i+1:>2}/{len(CUT_LIST)}] {cut.note:<28} "
              f"{cut.file} @ {cut.start}s +{cut.duration}s")
        normalize_segment(src, cut.start, cut.duration, dst)
        segments.append(dst)

    output = OUTPUT_DIR / "niagara_demo_v1.mp4"
    print(f"\nConcatenating -> {output}")
    concat_segments(segments, output)
    total = sum(c.duration for c in CUT_LIST)
    print(f"Done. Total length: {total:.1f}s")


if __name__ == "__main__":
    main()
