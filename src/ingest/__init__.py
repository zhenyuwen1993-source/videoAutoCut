"""Ingest stage: probe video, extract analysis frames, emit a manifest.

The ingest stage produces a low-fps frame stream used by every downstream
scorer (aesthetic, Chinese-CLIP semantic, shake). The original file is left
untouched and is referenced by render-time stages via the manifest.
"""

from .frame_extractor import (
    FrameManifest,
    FrameRecord,
    VideoMeta,
    extract_frames,
    probe_video,
)

__all__ = [
    "FrameManifest",
    "FrameRecord",
    "VideoMeta",
    "extract_frames",
    "probe_video",
]
