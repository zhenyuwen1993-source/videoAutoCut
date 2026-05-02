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

## Decisions to revisit when user provides footage

- GPU available? → if no, swap ViT-L for ViT-B and skip TransNetV2
- Whisper LLM rater: Qwen (DashScope key) or Claude API?
- Output format priority: short (30s) or long-form (3min vlog)?
- Music library: user-supplied, or fetch from Pixabay/uppbeat?

## Things explicitly NOT in scope

- Auto-publish to 小红书 / 抖音 (no public API for individuals — see project memory)
- AI-generated voiceover / AI-generated B-roll (this edits real footage only)
- Web UI (CLI / config-driven only — keep it lightweight)

## Reference research

See auto-memory `skill_video_highlight_detection.md` for the GitHub survey behind these choices.
