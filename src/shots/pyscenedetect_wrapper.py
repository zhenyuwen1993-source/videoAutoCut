"""PySceneDetect ContentDetector wrapper.

Cuts a video into shots using ``scenedetect.detect`` with the
``ContentDetector`` algorithm. Every output shot carries:

- ``shot_id``  (re-numbered after any later refinement)
- ``start_t / end_t / duration``  (seconds in the source timeline)
- ``start_frame / end_frame``  (indices into the *analysis*-fps frame
  stream produced by :mod:`src.ingest`, so downstream scorers can index
  the JPEGs directly with ``frames[start_frame:end_frame]``)

The companion :mod:`src.shots.transnetv2_refiner` post-processes the
output to merge too-short shots and (optionally) drop low-confidence
boundaries via TransNetV2.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scenedetect import ContentDetector, detect

from src.ingest import VideoMeta, probe_video


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Shot:
    """One detected shot.

    ``start_frame`` / ``end_frame`` are indices into the analysis-fps
    frame stream, NOT the source video's native frame numbers. End is
    exclusive (``frames[start:end]`` semantics).
    """

    shot_id: int
    start_t: float
    end_t: float
    duration: float
    start_frame: int
    end_frame: int


@dataclass
class ShotList:
    """Result container for one video's shot segmentation."""

    video: VideoMeta
    analysis_fps: float
    detector: str
    shots: list[Shot] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "video": asdict(self.video),
                "analysis_fps": self.analysis_fps,
                "detector": self.detector,
                "shots": [asdict(s) for s in self.shots],
            },
            ensure_ascii=False,
            indent=2,
        )

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def renumber(self) -> "ShotList":
        """Return a copy with ``shot_id`` re-issued in 0..N-1 order."""
        return ShotList(
            video=self.video,
            analysis_fps=self.analysis_fps,
            detector=self.detector,
            shots=[
                Shot(
                    shot_id=i,
                    start_t=s.start_t,
                    end_t=s.end_t,
                    duration=s.duration,
                    start_frame=s.start_frame,
                    end_frame=s.end_frame,
                )
                for i, s in enumerate(self.shots)
            ],
        )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_shots(
    video_path: str | Path,
    *,
    threshold: float = 27.0,
    min_scene_len_seconds: float = 1.0,
    analysis_fps: float = 2.0,
    show_progress: bool = False,
) -> ShotList:
    """Run PySceneDetect's ContentDetector and return a :class:`ShotList`.

    Parameters
    ----------
    video_path
        Source video on disk.
    threshold
        ContentDetector cut threshold. Lower = more cuts. 27.0 is the
        upstream default and works well for handheld travel footage.
    min_scene_len_seconds
        Cuts closer than this (in source timeline) are suppressed by
        ContentDetector. Converted to source-fps frames internally.
    analysis_fps
        Frame rate of the ingest-produced analysis stream. Used to map
        seconds to frame indices for downstream consumers.
    show_progress
        Forward to ``scenedetect.detect``'s progress flag.
    """
    video_path = Path(video_path).resolve()
    meta = probe_video(video_path)

    # ContentDetector's min_scene_len is in source-video frames.
    min_scene_frames = max(1, int(round(min_scene_len_seconds * (meta.fps or 30.0))))

    scene_list = detect(
        str(video_path),
        ContentDetector(threshold=threshold, min_scene_len=min_scene_frames),
        show_progress=show_progress,
    )

    shots: list[Shot] = []
    for i, (start_tc, end_tc) in enumerate(scene_list):
        start_t = float(start_tc.get_seconds())
        end_t = float(end_tc.get_seconds())
        shots.append(
            Shot(
                shot_id=i,
                start_t=round(start_t, 4),
                end_t=round(end_t, 4),
                duration=round(end_t - start_t, 4),
                start_frame=int(start_t * analysis_fps),
                end_frame=int(end_t * analysis_fps),
            )
        )

    # If PySceneDetect produced nothing (e.g. perfectly static footage),
    # fall back to a single shot covering the whole file so downstream
    # stages always have something to score.
    if not shots and meta.duration_seconds > 0:
        shots = [
            Shot(
                shot_id=0,
                start_t=0.0,
                end_t=round(meta.duration_seconds, 4),
                duration=round(meta.duration_seconds, 4),
                start_frame=0,
                end_frame=int(meta.duration_seconds * analysis_fps),
            )
        ]

    return ShotList(
        video=meta,
        analysis_fps=analysis_fps,
        detector="pyscenedetect",
        shots=shots,
    )
