"""v2 Niagara Falls demo: faster pace, hook montage, music, LUT, mild deshake.

Changes from v1:
- Pace: avg shot ~2.0s (was ~7s); 3-shot 0.4s hook montage; 55s total
- Music: Kevin MacLeod "Impact Andante" (CC BY 4.0) trimmed to 1st beat
- LUT: orange-teal cinematic at 75% strength (configurable)
- Transitions: hard cuts in body + 0.3s xfade at 3 major section breaks
- Deshake: ffmpeg `deshake` filter on handheld clips
- Color grade: mild S-curve + +sat, applied even without LUT
- Audio: original ducked -18dB under music
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
TEMP_DIR = OUTPUT_DIR / ".tmp_v2"
ASSETS_DIR = Path(r"D:\claudeWork\videoAutoCut\assets")
MUSIC = ASSETS_DIR / "music" / "impact_andante_kevin_macleod.mp3"
MUSIC_TRIM_START = 10.6  # first detected beat in the track
LUT = ASSETS_DIR / "luts" / "teal_orange.cube"  # filled in once downloaded
LUT_STRENGTH = 0.65  # 0=no LUT, 1=full Sam Kolder. 0.65 = cinematic but not radioactive


@dataclass
class Cut:
    file: str
    start: float
    duration: float
    deshake: bool = False
    note: str = ""


# Section markers indicate where to insert a 0.3s crossfade transition
# Total target: ~55s
CUT_LIST: list[Cut] = [
    # === HOOK (1.2s, 3x 0.4s rapid cuts) ===
    Cut("VID_20250721_105741_00_029.mp4",   1.0,  0.4, False, "hook 1: falls glimpse"),
    Cut("VID_20250721_104539_00_028.mp4", 446.0,  0.4, True,  "hook 2: mist surge"),
    Cut("VID_20250721_104221_00_023.mp4",   2.5,  0.4, False, "hook 3: foam macro"),

    # === XFADE BREAK -> ESTABLISHING (3s, the "we're at Niagara" reveal) ===
    Cut("VID_20250721_095610_00_012.mp4", 130.0,  3.0, False, "establish: tree + falls overlook"),

    # === BUILD-UP (16s, ~2s avg, hard cuts, narrative arc) ===
    Cut("VID_20250721_090234_00_007.mp4",   5.0,  2.0, False, "drive in"),
    Cut("VID_20250721_095610_00_012.mp4",  13.0,  2.0, True,  "walking park"),
    Cut("VID_20250721_095610_00_012.mp4", 100.0,  2.0, True,  "approaching falls visible"),
    Cut("VID_20250721_103653_00_022.mp4",  30.0,  2.0, True,  "red ponchos at dock"),
    Cut("VID_20250721_103259_00_021.mp4",   8.0,  2.0, True,  "boarding tunnel"),
    Cut("VID_20250721_103653_00_022.mp4", 148.0,  2.0, False, "dramatic clouds"),
    Cut("VID_20250721_104539_00_028.mp4",  60.0,  2.0, True,  "first approach: mist"),
    Cut("VID_20250721_104539_00_028.mp4", 350.0,  2.0, True,  "mist + lens flare"),

    # === XFADE BREAK -> CLIMAX (20s, money shots, slightly longer holds) ===
    Cut("VID_20250721_104539_00_028.mp4",  56.0,  3.0, True,  "[*]approach: mist + water power"),
    Cut("VID_20250721_105741_00_029.mp4",   0.0,  2.5, False, "[*]iconic wide w/ boat"),
    Cut("VID_20250721_104539_00_028.mp4", 446.0,  3.5, True,  "[*]falls feature: power"),
    Cut("VID_20250721_104221_00_023.mp4",   0.0,  2.5, False, "[*]macro: foam + mist"),
    Cut("VID_20250721_104539_00_028.mp4", 449.0,  3.0, True,  "[*]falls full force"),
    Cut("VID_20250721_104539_00_028.mp4", 645.0,  2.5, True,  "people watching"),
    Cut("VID_20250721_105741_00_029.mp4",   3.0,  2.5, False, "iconic continuation"),

    # === XFADE BREAK -> CLOSER (4s, personal moment) ===
    Cut("VID_20250721_104539_00_028.mp4", 547.0,  4.0, True,  "selfie smile (closer)"),
]

# Indices where a 0.3s crossfade should TRANSITION INTO the cut at that index.
# Disabled for v2.0: research shows short-form prefers hard cuts. The 0.05s
# audio fades + matching color grade across all clips already give a smooth feel.
# Re-enable by populating this set if user explicitly wants visible xfades.
XFADE_BEFORE_INDICES: set[int] = set()


def normalize_segment(cut: Cut, idx: int, dst: Path) -> None:
    """Re-encode a segment: deshake (optional) -> scale/pad -> blended LUT -> eq."""
    src = SOURCE_DIR / cut.file
    deshake = "deshake=x=-1:y=-1:w=-1:h=-1:rx=16:ry=16:edge=mirror," if cut.deshake else ""
    pre = (
        f"{deshake}"
        f"scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )
    post = "eq=saturation=1.05:contrast=1.03,fps=30"

    if LUT.exists() and LUT_STRENGTH > 0:
        # Partial-strength LUT via split + blend at LUT_STRENGTH opacity
        lut_rel = "assets/luts/teal_orange.cube"
        filter_complex = (
            f"[0:v]{pre},split=2[base][togr];"
            f"[togr]lut3d=file={lut_rel}[graded];"
            f"[base][graded]blend=all_mode=normal:all_opacity={LUT_STRENGTH},{post},"
        f"scale=in_range=full:out_range=tv:flags=accurate_rnd+full_chroma_int,"
        f"format=yuv420p[vout]"
        )
        af = (
            f"afade=t=in:st=0:d=0.05,"
            f"afade=t=out:st={max(cut.duration - 0.05, 0)}:d=0.05,"
            f"volume=-18dB"
        )
        cmd = [
            FFMPEG,
            "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(cut.start),
            "-i", str(src),
            "-t", str(cut.duration),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",
            "-af", af,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            str(dst),
        ]
    else:
        vf = (
            f"{pre},"
            "curves=preset=increase_contrast,"
            "eq=saturation=1.12:gamma=0.97:gamma_r=1.02:gamma_b=0.96,"
            "fps=30,"
            "scale=in_range=full:out_range=tv:flags=accurate_rnd+full_chroma_int,"
            "format=yuv420p"
        )
        af = (
            f"afade=t=in:st=0:d=0.05,"
            f"afade=t=out:st={max(cut.duration - 0.05, 0)}:d=0.05,"
            f"volume=-18dB"
        )
        cmd = [
            FFMPEG,
            "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(cut.start),
            "-i", str(src),
            "-t", str(cut.duration),
            "-vf", vf,
            "-af", af,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
            "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            str(dst),
        ]
    subprocess.run(cmd, check=True, cwd=Path(r"D:\claudeWork\videoAutoCut"))


def concat_with_xfades(segments: list[Path], xfade_indices: set[int], output: Path) -> None:
    """Concat segments with 0.3s crossfade at given indices, hard cut elsewhere.

    Approach: build a filter_complex that chains segments with xfade where needed,
    or concat demuxer where not. Simpler: if every transition is hard cut, just
    use concat demuxer (lossless). For xfades, fall back to filter_complex.
    """
    if not xfade_indices:
        # All hard cuts - use concat demuxer (fast, lossless)
        list_file = TEMP_DIR / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{s.as_posix()}'" for s in segments),
            encoding="utf-8",
        )
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output),
        ]
        subprocess.run(cmd, check=True)
        return

    # Build filter_complex for xfade transitions
    XFADE_DUR = 0.3
    inputs = []
    for s in segments:
        inputs.extend(["-i", str(s)])

    # Compute cumulative offset for each segment after applying xfades
    # When we xfade at index i, the timeline overlaps by XFADE_DUR
    parts = []
    last_label = "0:v"
    last_audio = "0:a"
    cum_time = 0.0
    # Get duration of each segment
    durations = []
    from json import loads
    for s in segments:
        probe = subprocess.run(
            [FFMPEG.replace("ffmpeg.exe", "ffprobe.exe"),
             "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(s)],
            capture_output=True, text=True, check=True,
        )
        durations.append(float(loads(probe.stdout)["format"]["duration"]))

    cum_time = durations[0]
    for i in range(1, len(segments)):
        out_label = f"v{i}"
        out_audio = f"a{i}"
        if i in xfade_indices:
            offset = cum_time - XFADE_DUR
            parts.append(
                f"[{last_label}][{i}:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}[{out_label}]"
            )
            parts.append(
                f"[{last_audio}][{i}:a]acrossfade=d={XFADE_DUR}[{out_audio}]"
            )
            cum_time += durations[i] - XFADE_DUR
        else:
            # Concat (no overlap)
            parts.append(
                f"[{last_label}][{i}:v]concat=n=2:v=1:a=0[{out_label}]"
            )
            parts.append(
                f"[{last_audio}][{i}:a]concat=n=2:v=0:a=1[{out_audio}]"
            )
            cum_time += durations[i]
        last_label = out_label
        last_audio = out_audio

    filter_complex = ";".join(parts)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-map", f"[{last_audio}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        str(output),
    ]
    subprocess.run(cmd, check=True)


def add_music(video: Path, music: Path, music_start: float, output: Path) -> None:
    """Mix music as background; original audio is already at -18dB.

    Music plays from `music_start` in the source track for the video's full
    duration, fading in 1.5s and out 2s.
    """
    # Probe video duration
    from json import loads
    probe = subprocess.run(
        [FFMPEG.replace("ffmpeg.exe", "ffprobe.exe"),
         "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    vid_dur = float(loads(probe.stdout)["format"]["duration"])

    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-ss", str(music_start), "-i", str(music),
        "-filter_complex",
        f"[1:a]atrim=duration={vid_dur},"
        f"afade=t=in:st=0:d=1.5,"
        f"afade=t=out:st={max(vid_dur-2, 0)}:d=2,"
        f"volume=0.7[bg];"
        f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k",
        str(output),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True)

    if not LUT.exists():
        print(f"[warn] LUT not found at {LUT}, falling back to curves+eq grade")

    segments: list[Path] = []
    for i, cut in enumerate(CUT_LIST):
        dst = TEMP_DIR / f"{i:02d}.mp4"
        flags = "+deshake" if cut.deshake else ""
        marker = " (xfade in)" if i in XFADE_BEFORE_INDICES else ""
        print(f"[{i+1:>2}/{len(CUT_LIST)}] {cut.note:<32} "
              f"{cut.file[-7:-4]} @ {cut.start:>5.1f}s +{cut.duration:>4.1f}s {flags}{marker}")
        normalize_segment(cut, i, dst)
        segments.append(dst)

    print("\nConcatenating with xfades...")
    silent_video = TEMP_DIR / "_silent.mp4"
    concat_with_xfades(segments, XFADE_BEFORE_INDICES, silent_video)

    print("Mixing music...")
    output = OUTPUT_DIR / "niagara_demo_v3.mp4"
    add_music(silent_video, MUSIC, MUSIC_TRIM_START, output)

    total = sum(c.duration for c in CUT_LIST) - 0.3 * len(XFADE_BEFORE_INDICES)
    print(f"\nDone. Output: {output}")
    print(f"Approx length: {total:.1f}s")


if __name__ == "__main__":
    main()
