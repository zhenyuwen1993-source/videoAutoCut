"""CLI entry: ``python -m src.shots <video> [opts]``.

Two ways to invoke:

* ``python -m src.shots input/trip.mp4`` — straight from the source.
* ``python -m src.shots --frames-dir output/trip_frames`` — read the
  ingest manifest and use its ``video.path`` / ``analysis_fps``.

Defaults come from ``configs/default.yaml::shots`` and can be
overridden by the flags below.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click
import yaml

from .pyscenedetect_wrapper import detect_shots
from .transnetv2_refiner import refine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def _resolve_video_from_frames_dir(frames_dir: Path) -> tuple[Path, float]:
    """Read ingest's manifest.json and return (video_path, analysis_fps)."""
    manifest_path = frames_dir / "manifest.json"
    if not manifest_path.exists():
        raise click.UsageError(f"manifest not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    video_path = Path(data["video"]["path"])
    analysis_fps = float(data.get("analysis_fps", 2.0))
    if not video_path.exists():
        raise click.UsageError(
            f"video referenced by manifest does not exist: {video_path}"
        )
    return video_path, analysis_fps


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "video",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
@click.option(
    "--frames-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Ingest output dir (containing manifest.json). Used to derive "
         "VIDEO and analysis_fps if VIDEO is omitted.",
)
@click.option(
    "-o",
    "--out-dir",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory. Default: output/<video-stem>_shots/",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=Path("configs/default.yaml"),
    show_default=True,
    help="YAML config to read defaults from.",
)
@click.option(
    "--threshold",
    type=float,
    default=None,
    help="ContentDetector threshold (override config).",
)
@click.option(
    "--min-duration",
    type=float,
    default=None,
    help="Minimum shot duration in seconds (override config). "
         "Shots shorter than this are merged into their left neighbor.",
)
@click.option(
    "--analysis-fps",
    type=float,
    default=None,
    help="Override the analysis fps used to compute frame indices. "
         "By default this is read from the frames-dir manifest, or "
         "from configs/default.yaml::ingest.analysis_fps.",
)
@click.option(
    "--refine/--no-refine",
    "do_refine",
    default=None,
    help="Run TransNetV2 GPU refine pass (default: from config).",
)
@click.option(
    "--transnetv2-confidence",
    type=float,
    default=None,
    help="TransNetV2 boundary-keep threshold (override config).",
)
@click.option(
    "--transnetv2-weights",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional path to TransNetV2 weights file.",
)
@click.option("--show-progress", is_flag=True, help="Show PySceneDetect progress bar.")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging.")
def main(
    video: Path | None,
    frames_dir: Path | None,
    out_dir: Path | None,
    config_path: Path,
    threshold: float | None,
    min_duration: float | None,
    analysis_fps: float | None,
    do_refine: bool | None,
    transnetv2_confidence: float | None,
    transnetv2_weights: Path | None,
    show_progress: bool,
    verbose: bool,
) -> None:
    """Segment VIDEO into shots and write shots.json."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if video is None and frames_dir is None:
        raise click.UsageError("provide VIDEO or --frames-dir")

    cfg = _load_config(config_path)
    cfg_shots = cfg.get("shots", {}) if isinstance(cfg, dict) else {}
    cfg_pyscene = cfg_shots.get("pyscenedetect", {})
    cfg_transnet = cfg_shots.get("transnetv2", {})
    cfg_ingest = cfg.get("ingest", {}) if isinstance(cfg, dict) else {}

    # ---- Resolve video / analysis_fps ----
    if video is None:
        assert frames_dir is not None
        video, manifest_fps = _resolve_video_from_frames_dir(frames_dir)
        if analysis_fps is None:
            analysis_fps = manifest_fps
    if analysis_fps is None:
        analysis_fps = float(cfg_ingest.get("analysis_fps", 2.0))

    # ---- Resolve detector params ----
    if threshold is None:
        threshold = float(cfg_pyscene.get("threshold", 27.0))
    min_scene_len_seconds = float(cfg_pyscene.get("min_scene_len_seconds", 1.0))
    if min_duration is None:
        min_duration = float(cfg_shots.get("min_shot_seconds", 1.2))
    if do_refine is None:
        do_refine = bool(cfg_transnet.get("enabled", True))
    if transnetv2_confidence is None:
        transnetv2_confidence = float(cfg_transnet.get("confidence_threshold", 0.5))

    # ---- Output dir ----
    if out_dir is None:
        out_dir = Path("output") / f"{video.stem}_shots"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Detect ----
    click.echo(
        f"[shots] {video}  →  {out_dir}  "
        f"(threshold={threshold}, min_dur={min_duration}, "
        f"analysis_fps={analysis_fps}, refine={do_refine})"
    )
    try:
        shot_list = detect_shots(
            video,
            threshold=threshold,
            min_scene_len_seconds=min_scene_len_seconds,
            analysis_fps=analysis_fps,
            show_progress=show_progress,
        )
    except Exception as exc:
        click.echo(f"[shots] ERROR during PySceneDetect: {exc}", err=True)
        sys.exit(1)

    click.echo(f"[shots] PySceneDetect produced {len(shot_list.shots)} shots")

    # ---- Refine ----
    refined = refine(
        shot_list,
        min_shot_seconds=min_duration,
        use_transnetv2=do_refine,
        transnetv2_confidence=transnetv2_confidence,
        transnetv2_weights=transnetv2_weights,
    )
    if refined.detector != shot_list.detector:
        click.echo(
            f"[shots] after refine ({refined.detector}): "
            f"{len(refined.shots)} shots"
        )

    # ---- Write ----
    out_path = out_dir / "shots.json"
    refined.write(out_path)
    click.echo(f"[shots] done. manifest at {out_path}")


if __name__ == "__main__":
    main()
