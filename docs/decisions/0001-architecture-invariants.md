# ADR-0001 — Architecture invariants

**Status**: accepted
**Date**: 2026-05-03
**Decided by**: Claude (consolidated parallel-session output) with MarchWen sign-off

## Context

Two independent Claude sessions built parts of `videoAutoCut` in parallel:

- **Desktop session** (this conversation) wrote demo cut scripts (v1→v3), the
  music+LUT fetcher, and a Phase-2 trip-level CLIP indexer using
  `open_clip ViT-B/32` against an inline 40-prompt English bank.
- **Dispatch / second session** built the canonical pipeline skeleton
  (`src/ingest`, `src/shots`, `configs/default.yaml`,
  `prompts/scenery.zh.txt`, `pyproject.toml`, `requirements.txt`) and
  locked in `Chinese-CLIP ViT-L/14`, Qwen rater, 3-min vlog target,
  MusicGen-small.

The two outputs **partially conflict**:

| Concern | Desktop session | Dispatch session | Conflict |
|---|---|---|---|
| Semantic model | `open_clip ViT-B/32` | `Chinese-CLIP ViT-L/14` | yes |
| Prompt bank | inline EN→ZH tuples in `media_indexer.py` | `prompts/scenery.zh.txt` (60+ ZH prompts) | yes |
| Dependency manifest | `requirements-clip.txt` (Phase-2 only) | `pyproject.toml` + `requirements.txt` | yes |
| Virtualenv layout | `.venv-clip/` (Phase-2 separate) | implicit `.venv/` (project main) | yes |
| Demo renders | `cut_demo.py`, `cut_demo_v2.py`, growing | not yet covered | none, but smell |

Without intervention, every future session will inherit the conflicts and
either pick a side at random or generate a third variant. That is what
"project degradation" looks like in this codebase.

## Decisions

### D-1. Phase-2 indexer adopts the canonical model + prompts

The trip-level indexer (`src/scoring/media_indexer.py`) is **kept as a
distinct tool** — its job (file-level tags across 1872 files) is genuinely
different from shot-level scoring (frame-level tags inside one video) — but
it must use the same model and the same prompt bank as the eventual
`src/scoring/semantic.py`.

- Model: `OFA-Sys/chinese-clip-vit-large-patch14` via `transformers`
- Prompts: read from `prompts/scenery.zh.txt` (skip blank + `#` lines)
- Frames per video: 3 (25%/50%/75% of duration), embeddings averaged
- Output: `data/media_index.json` with file-level top-K tags

**Alternative considered**: keep `ViT-B/32` for indexer speed (~30 min vs
~70 min for ViT-L/14 on 1872 files). Rejected because consistency between
trip-level and shot-level tags is more valuable than 40 minutes of
indexer runtime. The indexer runs once.

### D-2. `pyproject.toml` is the single source of truth for dependencies

- Edits go to `pyproject.toml` first.
- `requirements.txt` is a redundant snapshot kept for `pip install -r`
  workflows; updates must mirror `pyproject.toml`.
- `requirements-clip.txt` is **deleted**. Its content was a subset of
  what `pyproject.toml` already declares.
- `scripts/setup.sh` does the install in the right order (CUDA torch
  first via `--index-url`, then everything else).
- A single `.venv/` serves the entire project. The earlier `.venv-clip/`
  plan is abandoned.

### D-3. Models are downloaded incrementally, not all at once

`scripts/preload_models.sh` only downloads what the **currently
implemented** stages need:

- Chinese-CLIP ViT-L/14 (~900 MB) — used by indexer + future semantic
- LAION improved-aesthetic-predictor MLP (~3.5 MB)

Whisper / Silero VAD / MusicGen / TransNetV2 will be added to the preload
script when their respective `src/` modules become real code. This avoids
downloading 6 GB of weights for stages that may still get redesigned.

## Project invariants

These are the rules every session — desktop, Dispatch, future agents —
must read before editing.

### I-1. Single source of truth per concern

| Concern | Source of truth | Forbidden |
|---|---|---|
| Project deps | `pyproject.toml` | Hand-editing `requirements.txt` first; adding `requirements-*.txt` variants |
| Tunable params | `configs/default.yaml` | Hardcoded thresholds inside `src/` |
| Semantic prompt bank | `prompts/*.zh.txt` | Inline prompt lists in Python |
| Pipeline architecture | `CLAUDE.md` § Pipeline | Drift in code without doc update |
| Locked-in decisions | `CLAUDE.md` § Locked-in decisions | Re-litigating in code comments |
| Architecture changes | `docs/decisions/000N-*.md` (ADR) | Silent rewrites |

When a value or list shows up in two places, one of them is wrong.

### I-2. One CLIP, two granularities

`Chinese-CLIP ViT-L/14` is loaded once per process and reused for both:

- **File-level scoring** (trip indexer) — sample 3 frames per video, average embedding, top-K tags
- **Shot-level scoring** (semantic.py, future) — every shot's mid-frame, dense per-shot scores

Forbidden: a second CLIP variant loaded "for speed" or "for English." If
`L/14` is too slow, fix it once at the model layer (half precision, frame
downscale, smaller batch) — never fork the model choice.

### I-3. Demo scripts are throwaway, pipeline is the artifact

`src/assemble/cut_demo.py` and `cut_demo_v2.py` are scratch files for the
Niagara Falls demo (v1, v3). They will be deleted once `src/assemble/`
proper drives renders from EDL + config.

Forbidden: adding `cut_demo_v4.py`, `cut_demo_v5.py`, …. The next demo
improves the **pipeline**; new params go into `configs/default.yaml`.

### I-4. Models are project-local cached

Hugging Face / LAION / TransNetV2 weights live in `models/` (gitignored).
Bootstrap via `scripts/preload_models.sh` (idempotent).

Forbidden: scripts that pull weights to `~/.cache/huggingface/` without a
documented reason. The cache must be project-local so dispatching from
mobile produces the same state regardless of which user account runs the
task.

### I-5. Output format is forward-compatible H.264

All renders output `yuv420p tv-range bt709 H.264 high@4.1` (the v3 fix).
A render that changes pixel format must also update
`configs/default.yaml::export` AND ship a one-frame compatibility check
(the `ffmpeg -frames:v 1 -vf scale=480:-1 …` trick).

Forbidden: silently re-emerging `yuvj444p` outputs because some filter
chain reset the format. v3 already taught us this.

### I-6. Permissions live in one place, deliberately

`.claude/settings.local.json` either:

- has `"defaultMode": "bypassPermissions"` (preferred for this project), OR
- has a curated `allow` list with a comment block at the top explaining
  why each entry is there.

Forbidden: 50+ auto-accumulated `Bash(specific exact command...)` rules
from clicking "Always allow." When you see that, replace with
bypassPermissions and clean up.

### I-7. Memory hierarchy

| Layer | Lives in | Holds |
|---|---|---|
| Global | `~/.claude/.../MEMORY.md` | User identity, project pointers |
| Project | `CLAUDE.md` | Architecture, decisions, invariants |
| Module | docstrings + `docs/decisions/*.md` | Deep rationale |

Forbidden: stuffing project-specific memory into global, or
user-identity facts into `CLAUDE.md`.

## How to make changes safely

1. **Add a dependency**: edit `pyproject.toml`, then mirror to
   `requirements.txt`. Commit both in the same commit.
2. **Add a prompt**: append to `prompts/<bank>.zh.txt`, never to a Python
   list.
3. **Tune a threshold**: edit `configs/default.yaml`, never hardcode in a
   script.
4. **Add a pipeline stage**: create `src/<stage>/`, register it in
   `CLAUDE.md` § Pipeline, set defaults in `configs/default.yaml`.
5. **Make an architecture decision**: write `docs/decisions/000N-<slug>.md`
   with date, context, alternatives considered, decision, consequences.
6. **Add a model**: extend `scripts/preload_models.sh`. Don't rely on
   first-run auto-download from random call sites.

## Drift checks

These commands must pass before every commit. Add to a pre-commit hook
when one is set up.

```bash
# Exclusions skip the rule definitions themselves so the check doesn't
# match its own pattern in CLAUDE.md / this ADR.
EXCL=( ':!CLAUDE.md' ':!docs/decisions/' )

# No deleted-on-purpose files re-emerge
! git grep -n "requirements-clip" -- "${EXCL[@]}"

# No second CLIP variant outside ADRs
! git grep -nE "ViT-B-32|open_clip ViT-B" -- "${EXCL[@]}"

# Config still parses (run from inside .venv)
.venv/Scripts/python -c "import yaml; yaml.safe_load(open('configs/default.yaml'))"

# Shell scripts parse
for f in scripts/*.sh; do bash -n "$f"; done
```

## Consequences

- New sessions must read this file (linked from `CLAUDE.md`) before
  editing the project.
- The Niagara demo cut scripts (`cut_demo*.py`) are now formally on a
  deprecation path — they must be replaced by `src/assemble/` driven by
  EDL + config before any v4 render.
- The Phase-2 indexer's first run will be ~70 minutes (ViT-L/14 on 1872
  files), not ~30 (ViT-B/32). One-off cost; result is reusable across
  all future trip-level queries.
- Adding new external models now goes through `preload_models.sh` plus
  an ADR if the choice is non-obvious.
