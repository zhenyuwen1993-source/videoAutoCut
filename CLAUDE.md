# videoAutoCut

Auto-editor for MarchWen's travel footage. Output: short clips (30s–3min) for Douyin / 小红书 / YouTube.

## Core constraint

Most input is **silent scenery** (no dialogue). Transcript-based pipelines (the autoclip/mli-autocut family) do NOT apply as the primary engine. Voice handling is a secondary branch, not the main path.

## Invariants — read before editing

Multiple Claude sessions (desktop + Dispatch) edit this repo in parallel. To stay coherent, the following invariants hold. Full rationale: [`docs/decisions/0001-architecture-invariants.md`](docs/decisions/0001-architecture-invariants.md).

- **I-1. One source of truth per concern.** Deps → `pyproject.toml`. Tunables → `configs/default.yaml`. Prompts → `prompts/*.zh.txt`. Architecture → this file. Decisions → `docs/decisions/`. If a value lives in two places, one is wrong.
- **I-2. One CLIP, two granularities.** `Chinese-CLIP ViT-L/14` is the only CLIP. Used at file-level (trip indexer) and shot-level (semantic scorer). Don't fork the model "for speed" — tune at the model layer.
- **I-3. Demo scripts are throwaway.** `cut_demo*.py` will be deleted once `src/assemble/` drives from EDL+config. Don't add `cut_demo_v4.py`. Improve the pipeline; new params go in configs.
- **I-4. Models are project-local.** Weights live in `models/` (gitignored), bootstrapped by `scripts/preload_models.sh`. No `~/.cache/huggingface/`.
- **I-5. Output is yuv420p tv-range bt709 H.264 high@4.1.** Changing pixel format requires a config update AND a one-frame compatibility check.
- **I-6. Permissions deliberate.** `.claude/settings.local.json` either uses `bypassPermissions` mode, or has a curated commented allow list. No 50-rule auto-accumulation.
- **I-7. Memory hierarchy.** Global memory = user/project pointer. `CLAUDE.md` = architecture+decisions+invariants. ADRs = deep rationale. Don't mix layers.

**Drift checks** before every commit (run from project root, drift-check exclusions skip the rule definitions themselves):
```bash
EXCL=( ':!CLAUDE.md' ':!docs/decisions/' )
! git grep -n "requirements-clip" -- "${EXCL[@]}"
! git grep -nE "ViT-B-32|open_clip ViT-B" -- "${EXCL[@]}"
.venv/Scripts/python -c "import yaml; yaml.safe_load(open('configs/default.yaml'))"
for f in scripts/*.sh; do bash -n "$f"; done
```

How to make changes: see ADR-0001 § "How to make changes safely".

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
