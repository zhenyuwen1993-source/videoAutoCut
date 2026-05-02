"""Frame extraction core.

Decodes a video at ``analysis_fps`` (default 2 fps) using ffmpeg, writes JPEGs
to an output directory, and returns a :class:`FrameManifest` describing every
frame's path, frame index, and source timestamp in seconds.

The original file is never re-encoded — only sampled — so this is cheap to
re-run and the source remains usable for the final render.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import ffmpeg


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VideoMeta:
    """Container metadata returned by :func:`probe_video`."""

    path: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    codec: str
    has_audio: bool


@dataclass(frozen=True)
class FrameRecord:
    """One row in the frame manifest."""

    index: int                # 0-based frame index in the analysis stream
    timestamp: float          # second offset into the source video
    path: str                 # absolute path to the JPEG on disk


@dataclass
class FrameManifest:
    """All extracted analysis frames for one source video."""

    video: VideoMeta
    analysis_fps: float
    frames: list[FrameRecord] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "video": asdict(self.video),
                "analysis_fps": self.analysis_fps,
                "frames": [asdict(f) for f in self.frames],
            },
            ensure_ascii=False,
            indent=2,
        )

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def probe_video(video_path: str | Path) -> VideoMeta:
    """Return container/stream metadata using ``ffprobe``."""
    video_path = Path(video_path).resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    probe = ffmpeg.probe(str(video_path))
    streams = probe.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v_stream is None:
        raise ValueError(f"no video stream in {video_path}")

    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    # frame rate is reported as "30000/1001" etc.
    num, _, den = v_stream.get("avg_frame_rate", "0/1").partition("/")
    try:
        fps = float(num) / float(den) if float(den) else 0.0
    except ValueError:
        fps = 0.0

    duration = float(probe.get("format", {}).get("duration", 0.0))

    return VideoMeta(
        path=str(video_path),
        duration_seconds=duration,
        width=int(v_stream.get("width", 0)),
        height=int(v_stream.get("height", 0)),
        fps=fps,
        codec=str(v_stream.get("codec_name", "unknown")),
        has_audio=has_audio,
    )


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_frames(
    video_path: str | Path,
    out_dir: str | Path,
    *,
    analysis_fps: float = 2.0,
    jpeg_quality: int = 2,
    resize_long_edge: int = 720,
    overwrite: bool = True,
    write_manifest: bool = True,
) -> FrameManifest:
    """Decode ``video_path`` at ``analysis_fps`` and write JPEGs into ``out_dir``.

    Parameters
    ----------
    video_path
        Source video on disk.
    out_dir
        Directory for the extracted JPEGs and ``manifest.json``. Created if
        absent. If ``overwrite=True`` (default), an existing directory is
        wiped.
    analysis_fps
        Sample rate for the analysis stream. The pipeline default is 2 fps —
        enough temporal resolution for shot-level scoring, ~30× cheaper than
        decoding the full video.
    jpeg_quality
        ffmpeg ``-q:v`` (1 = best, 31 = worst). 2 keeps quality high without
        bloating disk.
    resize_long_edge
        If > 0, scales the longer side to this many pixels before encoding.
        Set to 0 to keep native resolution.
    overwrite
        Wipe ``out_dir`` if it already contains files.
    write_manifest
        Emit ``manifest.json`` alongside the frames.

    Returns
    -------
    FrameManifest
        With one :class:`FrameRecord` per JPEG.
    """
    video_path = Path(video_path).resolve()
    out_dir = Path(out_dir).resolve()

    meta = probe_video(video_path)

    if out_dir.exists() and overwrite:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = out_dir / "frame_%06d.jpg"

    # Build the ffmpeg graph: fps filter, optional scale, JPEG output.
    stream = ffmpeg.input(str(video_path)).filter("fps", fps=analysis_fps)
    if resize_long_edge and resize_long_edge > 0:
        # scale to long edge while preserving aspect; ``-1`` snaps to even.
        if meta.width >= meta.height:
            stream = stream.filter("scale", resize_long_edge, -2)
        else:
            stream = stream.filter("scale", -2, resize_long_edge)

    (
        stream
        .output(str(pattern), **{"q:v": jpeg_quality, "loglevel": "error"})
        .overwrite_output()
        .run(quiet=True)
    )

    # Build manifest from sorted file list (one row per JPEG actually written).
    jpgs = sorted(out_dir.glob("frame_*.jpg"))
    records = [
        FrameRecord(
            index=i,
            timestamp=round(i / analysis_fps, 4),
            path=str(p),
        )
        for i, p in enumerate(jpgs)
    ]
    manifest = FrameManifest(video=meta, analysis_fps=analysis_fps, frames=records)

    if write_manifest:
        manifest.write(out_dir / "manifest.json")

    return manifest
