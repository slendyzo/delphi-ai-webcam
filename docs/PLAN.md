# Delphi AI Webcam — Animated Anon-Guest Pipeline

## Executive Summary

Some podcast guests want to stay visually anonymous. Instead of showing a static image, this project animates a custom illustration (e.g., a Shakespeare portrait for a guest called "signüll") to lip-sync with the guest's voice, giving viewers visual feedback that someone is speaking. We're matching the same approach the **a16z Show** uses — that podcast uses **Hedra Character-3**, an AI model a16z themselves invested $32M in.

**Deliverable:** A simple cross-platform (Mac/Windows) script, stored in a GitHub repo. The user drops a webcam recording into `in/`, runs one command, picks a character from a menu, and an animated MP4 lands in `out/` — same duration, same audio, same frame count as the input. During silent gaps the character holds a still pose (no AI cost spent on silence).

**Cost:** ~$65 at 480p or ~$98 at 720p per 60-minute episode (with silence trimming).

**Approval asked for:** The design below, targeting Hedra Character-3. Once approved, this plan is copied to `docs/PLAN.md` in the project repo so it can be shared before implementation begins.

---

## Why Hedra

The a16z Show uses Hedra Character-3 for exactly this pattern (pseudonymous guest represented by a custom illustration). Evidence:

- a16z led Hedra's $32M Series A and publicly calls Character-3 "best-in-class for most use cases" in their own benchmarking ([a16z.com/ai-avatars](https://a16z.com/ai-avatars/))
- TechCrunch describes Hedra as "the app used to make talking baby podcasts"
- Hedra Character-3 outputs phoneme-accurate lip-sync, micro-expressions (blinks, eyebrow raises, gaze shifts), and natural head motion — matching what you see in the signüll/Shakespeare clip

**Key constraint:** Hedra Character-3 accepts a maximum of **60 seconds of audio per API call**. Podcast segments are 45–75 minutes, so the pipeline chunks audio at silence boundaries, submits chunks in parallel, and stitches the results back together with the original timeline preserved exactly.

---

## Cost Context (for the boss conversation)

Cost per 60-minute guest segment, 33% silence assumed (40 min = 2,400 sec of speech actually sent to Hedra):

| Option | Cost/episode | Quality | Notes |
|---|---|---|---|
| **Hedra Character-3 @ 720p (chosen)** | **~$98** | **Top tier. Matches a16z exactly.** | Pro plan credit rate, ~$0.041/sec |
| Hedra Character-3 @ 480p | ~$65 | Same motion quality, lower pixel resolution | Same credit rate at lower tier |
| fal.ai Fabric 1.0 @ 480p | ~$192 | Good lip-sync, less expressive motion | Alternative considered, more expensive |
| fal.ai Fabric 1.0 @ 720p | ~$360 | Same as above | Not competitive vs Hedra |
| Replicate SadTalker | ~$5–10 | 2022-era quality, noticeably AI, stiff motion | Could be added later for testing; viewer would notice the quality drop |
| Self-hosted Hallo2 on cloud GPU | ~$2–5 | Good, supports 1-hour segments in one pass | High setup complexity, rejected for v1 |

**Monthly cost projections at 720p:**

| Episodes/month | Cost |
|---|---|
| 2 | ~$196 |
| 4 | ~$392 |
| 8 | ~$784 |

**Hedra plans:**
- Creator ($30/mo, ~10 min of 720p generation)
- Pro ($75/mo, ~30 min of 720p generation)
- Enterprise (custom pricing, needed for regular podcast use)

A single 60-min episode exceeds the Pro plan's monthly credits. For regular production use we'd either negotiate Enterprise pricing or stay on Pro and pay overage credits.

**Cost-reduction levers built into the pipeline:**
- **Silence trimming** eliminates ~33% of spend automatically (no AI cost during silent gaps).
- **Chunk-level cache** makes re-runs free (if you re-render with a different character image, previously-generated chunks are reused where possible).
- **Cost preview prompt** forces explicit `[y/N]` confirmation before any API calls — accidental runs cost $0.
- **Resolution flag** (`--resolution 480p`) cuts cost ~35% when testing or for episodes where 720p isn't needed.

---

## How It Works

### User experience

```
$ uv run delphi
  Scanning in/ ...
  Found: episode-42-guest.mp4 (01:04:17)

  Pick a character:
    › shakespeare.png
      astronaut.png
      robot.png

  ✓ Selected: shakespeare

  Analyzing audio ...
    67% speech, 33% silence
    → 42 speech chunks to animate
    → 38 silence segments (held as still frames, no AI cost)

  Estimated cost: ~$98 (14,400 Hedra credits at 720p)
  Proceed? [y/N] › y

  Rendering [##########-------] 26/42 chunks | ETA 11m

  ✓ Done in 23m 4s
  → out/episode-42-guest_shakespeare.mp4 (01:04:17)
```

### Processing pipeline

```
 in/episode42.mp4  ─┐
                    ▼
           [1] Extract audio (ffmpeg)
                    ▼
           [2] Detect silence → [speech], [silence], [speech], ...
                    ▼
           [3] Split long speech intervals at internal silence (≤60s chunks)
                    ▼
           [4] Preview total cost, confirm [y/N]
                    ▼
           [5] Submit speech chunks to Hedra in parallel (semaphore = 4)
               Cache by (audio hash + image hash) — re-runs are free
                    ▼
           [6] Render silence placeholders: still image as video at matching FPS
                    ▼
           [7] Concatenate all clips in timeline order (ffmpeg concat demuxer)
                    ▼
           [8] Mux the original audio back in (untouched)
                    ▼
 out/episode42_shakespeare.mp4
```

**Key guarantees:** output duration = input duration (exact frame count match), output audio = input audio (untouched), silent gaps cost nothing, re-runs are cached.

### Step details

- **[1] Audio extract** — `ffmpeg -i in.mp4 -vn -acodec pcm_s16le -ar 24000 -ac 1 audio.wav`. 24kHz mono matches Hedra's expected input.
- **[2] Silence detection** — `ffmpeg -i audio.wav -af silencedetect=noise=-30dB:d=1.5 -f null -` and parse stderr for `silence_start` / `silence_end` events. Threshold of −30dB over 1.5s gives a good speech/silence boundary for podcast audio.
- **[3] Chunking** — For each speech interval longer than 60s, look for internal silence ≥ 200ms to split at. If none exists (someone monologues non-stop for >60s), hard-cut at 59.5s. Log hard cuts so they can be eyeballed in the final output.
- **[4] Cost preview** — Sum chunk seconds × 6 credits/sec (720p) or 4 credits/sec (480p). Convert to dollars at Pro plan's credit rate. Prompt for confirmation.
- **[5] Hedra submission** — Async task per chunk with `asyncio.Semaphore(4)` for rate-limit safety. Each task: POST image + audio chunk → poll status endpoint (Hedra is queue-based) → download the MP4 to `.cache/chunks/<hash>.mp4`. If `<hash>.mp4` already exists, skip the API call entirely. Retry 3× with exponential backoff on transient failures.
- **[6] Silence placeholders** — For each silence interval: `ffmpeg -loop 1 -t <dur> -i characters/<name>.png -c:v libx264 -pix_fmt yuv420p -r <fps> -vf scale=1280:720 -an .cache/silence/<hash>.mp4`. Probe one Hedra chunk first to match its FPS exactly.
- **[7] Concat** — Build `concat.txt` in timeline order, then `ffmpeg -f concat -safe 0 -i concat.txt -c copy stitched.mp4`. Fall back to re-encoding only if parameters don't match.
- **[8] Final mux** — `ffmpeg -i stitched.mp4 -i original_audio.wav -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -shortest out/<input_name>_<character>.mp4`. Discards Hedra's per-chunk audio tracks (which are the same source re-encoded) and uses the pristine original.

---

## Architecture

### Folder layout

```
delphi_ai_webcam/
├── in/                       # input videos (gitignored, keeps .gitkeep)
├── out/                      # rendered results (gitignored, keeps .gitkeep)
├── characters/               # illustrations (tracked in git so portable)
│   ├── shakespeare.png
│   ├── astronaut.png
│   └── robot.png
├── docs/
│   └── PLAN.md               # copy of this plan, readable by team/boss
├── src/
│   ├── main.py               # entry point, CLI prompts, orchestration
│   ├── audio.py              # extract audio, detect silence, chunk
│   ├── video.py              # still-frame render, concat, final mux
│   ├── hedra.py              # Hedra API client (submit, poll, download, retry)
│   ├── cache.py              # hash-based chunk cache
│   └── config.py             # .env loading, paths, constants
├── .cache/                   # generated chunks (gitignored)
├── .env.example              # HEDRA_API_KEY=
├── .gitignore
├── pyproject.toml            # uv-managed, Python 3.11+
├── uv.lock
└── README.md
```

### Stack

| Piece | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Cross-platform, best ffmpeg tooling, simple to tweak |
| Package manager | [uv](https://docs.astral.sh/uv/) | One tool installs Python + deps on Mac/Windows. `uv sync` once, `uv run delphi` every run |
| Video/audio | system `ffmpeg` binary | Via `subprocess` with argv lists (no shell quoting) |
| Silence detection | ffmpeg `silencedetect` filter | Built in, no extra dep |
| Hedra API | `httpx` (async) | Parallel chunk submission |
| CLI prompts | `questionary` | Arrow-key character picker, works on Mac and Windows |
| Progress display | `rich` | Pretty progress bar |
| Env loading | `python-dotenv` | `.env` file support |

### Future swap-out

Hedra is the only backend for v1, but the code isolates all Hedra-specific calls in `src/hedra.py` (one file with ~3 functions: `submit_chunk`, `poll_until_done`, `download_result`). If we ever want to test a cheaper or different model, replacing that single file is the scope — not a refactor.

---

## Critical Files to Create

All paths relative to `/Users/slendyzo/Desktop/delphi_ai_webcam/`:

| File | Purpose |
|---|---|
| `pyproject.toml` | uv project config, Python 3.11+, deps: `httpx`, `python-dotenv`, `questionary`, `rich` |
| `src/main.py` | Entry point: scan `in/`, prompt character, orchestrate pipeline, print progress |
| `src/config.py` | Load `.env`, resolve paths, constants (credit rates, chunk size, silence threshold) |
| `src/audio.py` | `extract_audio()`, `detect_silence()`, `chunk_speech_intervals()` |
| `src/hedra.py` | Async `submit_chunk()`, `poll_until_done()`, `download_result()`, retry with backoff |
| `src/video.py` | `render_silence_placeholder()`, `concat_clips()`, `mux_original_audio()` |
| `src/cache.py` | Hash-keyed chunk cache so re-runs skip completed work |
| `.env.example` | `HEDRA_API_KEY=` |
| `.gitignore` | `in/*`, `out/*` (keep `.gitkeep`), `.cache/`, `.env`, `__pycache__/`, `*.pyc`, `.venv/` |
| `README.md` | Setup (install ffmpeg + uv), Hedra sign-up walkthrough, usage, cost table, troubleshooting |
| `characters/.gitkeep` | Empty placeholder so the folder exists on clone |
| `docs/PLAN.md` | This document, copied into the repo for sharing |

---

## Verification

End-to-end smoke test (requires a Hedra API key — will spend ~$2–3 on a short test):

1. Install prerequisites: `brew install ffmpeg uv` (Mac) or `winget install ffmpeg astral-sh.uv` (Windows)
2. `git clone <repo> && cd delphi_ai_webcam && uv sync`
3. `cp .env.example .env` and paste Hedra API key
4. Drop a 2–3 minute test video into `in/`
5. Drop a character PNG into `characters/` (portrait crop, ideally 1024×1024 or larger)
6. `uv run delphi`
7. Confirm the cost prompt shows a sensible estimate (~$5 for a 3-minute clip)
8. Accept, wait for completion
9. Play `out/<name>_<character>.mp4`: audio matches original, mouth moves during speech, holds still during silence, duration matches input within one frame

Edge cases to verify:

- Very long speech with no internal pauses (tests hard-cut boundary smoothness)
- Mostly-silent video (tests still-frame placeholder rendering and cost savings)
- Re-running the same input (tests cache hit rate → near-zero API calls on second run)
- Missing `.env` (friendly error with pointer to `.env.example`)
- Missing ffmpeg (friendly error with OS-specific install hint)
- `Ctrl-C` mid-run (partial cache preserved, next run resumes from where it stopped)

---

## What Happens After Approval

1. This plan is copied from its Claude Code location to `docs/PLAN.md` in the project repo, so you (and your boss) can read it at the source.
2. A README is written with setup instructions, Hedra sign-up walkthrough, and the cost table above.
3. The scaffold (`src/`, `pyproject.toml`, `.env.example`, `.gitignore`, folder structure) is built.
4. The Hedra backend and audio pipeline are implemented.
5. A GitHub repo is initialized (private or public per user's preference) and pushed.
6. A short real-world test (2–3 min clip) is processed end-to-end to validate cost estimates, timing, and caching behavior.
7. Once validated, a real-length episode is processed to confirm the full pipeline works at production length.

---

## Out of Scope

- Speaker diarization (inputs are already guest-only per-track recordings)
- Side-by-side or composited output (user composites in Premiere/Resolve as part of the podcast edit)
- Face-masking replacement in the original webcam frame (much more complex, different class of model)
- Real-time / live streaming
- Auto-generating character illustrations from a text prompt
- GUI — the CLI + folder-drop workflow is the target
