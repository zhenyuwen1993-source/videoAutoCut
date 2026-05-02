"""CLI entry: ``python -m src.ingest <video> [opts]``.

Decodes a video at the configured analysis fps and writes JPEG frames + a
manifest. Defaults align with ``configs/default.yaml::ingest``.

Examples
--------
::

    # quick run with defaults (2 fps, long-edge 720 px)
    python -m src.ingest input/trip.mp4

    # custom output dir, native resolution, 1 fps
    python -m src.ingest input/trip.mp4 -o output/trip_frames --fps 1 --no-resize
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .frame_extractor import extract_frames, probe_video


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--out-dir",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory. Default: output/<video-stem>_frames/",
)
@click.option(
    "--fps",
    "analysis_fps",
    type=float,
    default=2.0,
    show_default=True,
    help="Analysis frame rate.",
)
@click.option(
    "--quality",
    "jpeg_quality",
    type=click.IntRange(1, 31),
    default=2,
    show_default=True,
    help="ffmpeg JPEG quality (1=best, 31=worst).",
)
@click.option(
    "--resize",
    "resize_long_edge",
    type=int,
    default=720,
    show_default=True,
    help="Long-edge pixel size. Use --no-resize to keep native resolution.",
)
@click.option("--no-resize", "no_resize", is_flag=True, help="Disable resizing.")
@click.option(
    "--keep-existing",
    is_flag=True,
    help="Don't wipe the output directory before extracting.",
)
@click.option("--probe-only", is_flag=True, help="Print metadata and exit; don't extract.")
def main(
    video: Path,
    out_dir: Path | None,
    analysis_fps: float,
    jpeg_quality: int,
    resize_long_edge: int,
    no_resize: bool,
    keep_existing: bool,
    probe_only: bool,
) -> None:
    """Extract analysis frames from VIDEO."""
    if probe_only:
        meta = probe_video(video)
        click.echo(
            f"{meta.path}\n"
            f"  duration : {meta.duration_seconds:.2f} s\n"
            f"  size     : {meta.width}x{meta.height}\n"
            f"  fps      : {meta.fps:.3f}\n"
            f"  codec    : {meta.codec}\n"
            f"  audio    : {'yes' if meta.has_audio else 'no'}"
        )
        return

    if out_dir is None:
        # default to <repo>/output/<stem>_frames
        out_dir = Path("output") / f"{video.stem}_frames"

    if no_resize:
        resize_long_edge = 0

    click.echo(f"[ingest] {video}  →  {out_dir}  (fps={analysis_fps})")
    try:
        manifest = extract_frames(
            video,
            out_dir,
            analysis_fps=analysis_fps,
            jpeg_quality=jpeg_quality,
            resize_long_edge=resize_long_edge,
            overwrite=not keep_existing,
            write_manifest=True,
        )
    except Exception as exc:  # surface ffmpeg / IO errors with nonzero exit
        click.echo(f"[ingest] ERROR: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"[ingest] done. {len(manifest.frames)} frames, "
        f"manifest at {out_dir / 'manifest.json'}"
    )


if __name__ == "__main__":
    main()
