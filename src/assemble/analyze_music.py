"""Detect BPM and beat times from a music track.

Outputs JSON to stdout:
{ "tempo": 95.7, "duration": 247.3, "beats": [0.42, 1.05, ...] }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import librosa
import numpy as np


def analyze(track_path: Path) -> dict:
    y, sr = librosa.load(str(track_path), mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    tempo_val = float(np.atleast_1d(tempo)[0])
    return {
        "tempo": tempo_val,
        "duration": float(len(y) / sr),
        "beats": [round(float(t), 4) for t in beat_times],
    }


if __name__ == "__main__":
    path = Path(sys.argv[1])
    result = analyze(path)
    summary = {
        "tempo": result["tempo"],
        "duration": result["duration"],
        "beat_count": len(result["beats"]),
        "first_10_beats": result["beats"][:10],
    }
    print(json.dumps(summary, indent=2))
    out = path.with_suffix(".beats.json")
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nFull beat list saved to: {out}")
