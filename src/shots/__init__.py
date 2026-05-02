"""Shot segmentation: source video → list of shots with timestamps.

CPU pass uses PySceneDetect's ContentDetector. An optional GPU refine
pass (TransNetV2) drops low-confidence cuts. A pure-Python fallback
``enforce_min_duration`` always runs and merges flicker-short shots.
"""

from .pyscenedetect_wrapper import Shot, ShotList, detect_shots
from .transnetv2_refiner import (
    enforce_min_duration,
    refine,
    refine_with_transnetv2,
)

__all__ = [
    "Shot",
    "ShotList",
    "detect_shots",
    "enforce_min_duration",
    "refine",
    "refine_with_transnetv2",
]
