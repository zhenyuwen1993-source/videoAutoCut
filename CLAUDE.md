# videoAutoCut

Auto-editor for MarchWen's travel footage. Output: short clips (30s–3min) for Douyin / 小红书 / YouTube.

## Core constraint

Most input is **silent scenery** (no dialogue). Transcript-based pipelines (the autoclip/mli-autocut family) do NOT apply as the primary engine. Voice handling is a secondary branch, not the main path.

## Pipeline

```
INGEST                ffmpeg-python decode at 2 fps for analysis, original kept for render
SHOT SEGMENTATION     PySceneDetect (CPU pass) → TransNetV2 (GPU refine, optional)
PER-SHOT SCORING
  ├─ aesthetic        improved-aesthetic-predictor (LAION MLP on CLIP ViT-L/14)
  ├─ semantic         Chinese-CLIP or SigLIP 2 vs prompt bank (风景 / 美食 / 街景 / 人物 / 夜景 / 建筑)
  └─ shake penalty    optical flow magnitude (cv2.calcOpticalFlowFarneback)
VOICE BRANCH          (parallel, only if Silero VAD detects voice)
  Silero VAD → WhisperX (faster-whisper backend) → LLM rates utterance interestingness
SELECTION             greedy top-N with diversity penalty (CLIP-embedding distance)
ASSEMBLY              moviepy or raw ffmpeg + librosa beat-snap (±150ms)
EXPORT                9:16 (Douyin/小红书) + 16:9 (YouTube) ladder
```

Scoring formula:
```
shot_score = w_a * aesthetic + w_s * max(prompt_sim) + w_v * voice_score - w_m * shake
```

## Project layout

```
src/
  ingest/        — ffmpeg decode helpers, frame sampling
  shots/         — PySceneDetect / TransNetV2 wrappers
  scoring/       — aesthetic, semantic (CLIP), shake
  voice/         — VAD + ASR + LLM utterance rating
  select/        — top-N + diversity
  assemble/      — moviepy / ffmpeg concat + beat-snap
  export/        — aspect-ratio ladders, subtitle burn-in
input/           — raw footage (gitignored)
output/          — generated clips (gitignored)
prompts/         — Chinese prompt banks for semantic scoring
configs/         — scoring weights, target durations
```

## Locked-in decisions (2026-05-02)

- **GPU**: available — use **ViT-L/14** for both aesthetic predictor and Chinese-CLIP semantic scoring. **TransNetV2 enabled** as the GPU refine pass after PySceneDetect.
- **Voice utterance rater**: **Qwen via DashScope** (default `qwen-plus`). Reason: native Chinese, low cost, sufficient for "rate 1–10" scoring. `anthropic` Claude SDK is wired in as a fallback rater (switch via `configs/default.yaml::voice.rater.provider`).
- **Output target**: **3-minute vlog** is the priority format. `select.target_total_seconds: 180`, target shot count 25–45. Short formats (30s/60s) are derived later from the same EDL.
- **Background music**: **generated locally**, not fetched from libraries.
  - Initial engine: **Meta MusicGen-small** via the `audiocraft` package. Rationale: runs locally on the same GPU, MIT-friendly, simple API, ~3GB VRAM, ~30 s synthesis for a 200 s track. Quality is acceptable for vlog beds.
  - Prompt strategy: a default cinematic/acoustic prompt + per-scene-cluster overrides keyed on the dominant Chinese semantic tag (see `configs/default.yaml::music.prompt_overrides_by_scene`).
  - **TODO**: evaluate Stable Audio Open and ACE-Step as upgrade paths once the MVP runs end-to-end.

## Config

- All tunables live in `configs/default.yaml`.
- Chinese semantic prompt bank: `prompts/scenery.zh.txt`.
- Raw footage: `input/` (gitignored). Renders + manifests: `output/` (gitignored).
- Dependencies pinned in `requirements.txt` and `pyproject.toml`. GPU torch via `--extra-index-url https://download.pytorch.org/whl/cu121`.

## Implementation status

- [x] Project skeleton, .venv, packaging files
- [x] `configs/default.yaml`, `prompts/scenery.zh.txt`
- [x] `src/ingest/` — ffmpeg frame extraction at 2 fps + CLI
- [x] `src/shots/` — PySceneDetect wrapper + min-duration merge + optional TransNetV2 refine + CLI
- [ ] `src/scoring/` — aesthetic + Chinese-CLIP semantic + shake
- [ ] `src/voice/` — Silero VAD + WhisperX + Qwen rater
- [ ] `src/select/` — greedy top-N with diversity, 3-min target
- [ ] `src/assemble/` — moviepy/ffmpeg concat + librosa beat-snap + ducking
- [ ] `src/export/` — 9:16 + 16:9 ladder, subtitle burn-in
- [ ] Background-music branch — MusicGen-small integration

## Decisions to revisit later

- MusicGen → Stable Audio Open / ACE-Step swap once footage is in
- Whether TransNetV2 actually adds value over PySceneDetect alone (ablate after first batch)
- Whether `qwen-turbo` is good enough vs `qwen-plus` (cost vs quality)

## Things explicitly NOT in scope

- Auto-publish to 小红书 / 抖音 (no public API for individuals — see project memory)
- AI-generated voiceover / AI-generated B-roll (this edits real footage only)
- Web UI (CLI / config-driven only — keep it lightweight)

## Reference research

See auto-memory `skill_video_highlight_detection.md` for the GitHub survey behind these choices.
