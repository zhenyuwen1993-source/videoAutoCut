"""Post-processing of PySceneDetect output.

Two responsibilities:

1.  ``enforce_min_duration`` — pure-Python, always available. Merges
    each too-short shot into its left neighbor so the downstream scorer
    isn't forced to rate 0.4-second flickers.
2.  ``refine_with_transnetv2`` — optional GPU pass. Loads the
    TransNetV2 model (if installed) and drops PySceneDetect cuts whose
    boundary frame has confidence below
    ``configs/default.yaml::shots.transnetv2.confidence_threshold``,
    merging the adjacent shots. If TransNetV2 is not importable, the
    function logs a warning and returns the input unchanged — never
    raises.

TransNetV2 has no PyPI release; install from source if you want the
GPU refine pass to fire::

    pip install git+https://github.com/soCzech/TransNetV2.git
"""

from __future__ import annotations

import logging
from pathlib import Path

from .pyscenedetect_wrapper import Shot, ShotList

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure-Python: merge short shots
# ---------------------------------------------------------------------------

def _merge(left: Shot, right: Shot) -> Shot:
    return Shot(
        shot_id=left.shot_id,  # re-numbered by ShotList.renumber afterwards
        start_t=left.start_t,
        end_t=right.end_t,
        duration=round(right.end_t - left.start_t, 4),
        start_frame=left.start_frame,
        end_frame=right.end_frame,
    )


def enforce_min_duration(shot_list: ShotList, min_seconds: float) -> ShotList:
    """Return a copy of ``shot_list`` with no shot shorter than ``min_seconds``.

    Strategy: walk left-to-right; whenever the running tail is shorter
    than the threshold, merge the next shot into it. After the pass,
    if the final shot is still too short, merge it into its predecessor.
    Single-shot lists are returned unchanged.
    """
    if min_seconds <= 0 or len(shot_list.shots) <= 1:
        return shot_list

    out: list[Shot] = [shot_list.shots[0]]
    for s in shot_list.shots[1:]:
        if out[-1].duration < min_seconds:
            out[-1] = _merge(out[-1], s)
        else:
            out.append(s)

    if len(out) >= 2 and out[-1].duration < min_seconds:
        last = out.pop()
        out[-1] = _merge(out[-1], last)

    return ShotList(
        video=shot_list.video,
        analysis_fps=shot_list.analysis_fps,
        detector=shot_list.detector + "+min_dur",
        shots=out,
    ).renumber()


# ---------------------------------------------------------------------------
# Optional GPU refine: drop low-confidence cuts via TransNetV2
# ---------------------------------------------------------------------------

def _try_import_transnetv2():
    """Try to import the TransNetV2 entry point. Return None if unavailable."""
    try:
        from transnetv2 import TransNetV2  # type: ignore
        return TransNetV2
    except ImportError:
        return None


def refine_with_transnetv2(
    shot_list: ShotList,
    *,
    confidence_threshold: float = 0.5,
    weights_path: str | Path | None = None,
) -> ShotList:
    """Drop PySceneDetect cuts with weak TransNetV2 confidence.

    Implementation note
    -------------------
    TransNetV2 returns a per-frame "is-this-a-shot-boundary" probability
    when run on the source video. For each PySceneDetect cut we look up
    that probability at the exact boundary frame; cuts below
    ``confidence_threshold`` are deleted (the two adjacent shots are
    merged). This is a low-risk refinement because it can only **remove**
    cuts, never invent new ones.

    If TransNetV2 isn't installed, this function logs a warning and
    returns ``shot_list`` unchanged.
    """
    TransNetV2 = _try_import_transnetv2()
    if TransNetV2 is None:
        log.warning(
            "TransNetV2 not installed — skipping GPU refine pass. "
            "Install with: pip install git+https://github.com/soCzech/TransNetV2.git"
        )
        return shot_list

    if len(shot_list.shots) <= 1:
        return shot_list

    try:
        model = TransNetV2() if weights_path is None else TransNetV2(weights_path)
        # ``predict_video`` returns single-frame & all-frame probability arrays.
        _, single_frame_pred, _ = model.predict_video(shot_list.video.path)
    except Exception as exc:  # noqa: BLE001 — never let optional path crash pipeline
        log.warning("TransNetV2 inference failed (%s); skipping refine.", exc)
        return shot_list

    src_fps = shot_list.video.fps or 30.0
    kept: list[Shot] = [shot_list.shots[0]]
    for s in shot_list.shots[1:]:
        cut_frame = int(round(s.start_t * src_fps))
        cut_frame = max(0, min(cut_frame, len(single_frame_pred) - 1))
        confidence = float(single_frame_pred[cut_frame])
        if confidence >= confidence_threshold:
            kept.append(s)
        else:
            log.debug(
                "transnetv2: drop cut at %.3fs (frame %d, conf %.3f < %.2f)",
                s.start_t, cut_frame, confidence, confidence_threshold,
            )
            kept[-1] = _merge(kept[-1], s)

    return ShotList(
        video=shot_list.video,
        analysis_fps=shot_list.analysis_fps,
        detector=shot_list.detector + "+transnetv2",
        shots=kept,
    ).renumber()


# ---------------------------------------------------------------------------
# Top-level convenience
# ---------------------------------------------------------------------------

def refine(
    shot_list: ShotList,
    *,
    min_shot_seconds: float = 1.2,
    use_transnetv2: bool = True,
    transnetv2_confidence: float = 0.5,
    transnetv2_weights: str | Path | None = None,
) -> ShotList:
    """Apply the full refine pipeline: TransNetV2 (optional) → min-duration."""
    refined = shot_list
    if use_transnetv2:
        refined = refine_with_transnetv2(
            refined,
            confidence_threshold=transnetv2_confidence,
            weights_path=transnetv2_weights,
        )
    refined = enforce_min_duration(refined, min_shot_seconds)
    return refined
