# Delphi AI Webcam

Animate a custom illustration to lip-sync with a webcam recording, for anonymous podcast guests. Matches the avatar pattern the a16z Show uses when guests like signüll appear pseudonymously.

Drop a webcam recording into `in/`, pick a character from `characters/`, run one command, and a lip-synced MP4 lands in `out/` — same duration, same audio, same frame count as the input. Silent gaps hold a still frame so you only pay for AI where the guest is actually speaking.

Uses [Hedra Character-3](https://www.hedra.com) for the animation. See [docs/PLAN.md](docs/PLAN.md) for full design rationale.

---

## Prerequisites

You need **ffmpeg** and **uv** installed on your system.

**Mac:**
```bash
brew install ffmpeg uv
```

**Windows:**
```powershell
winget install ffmpeg astral-sh.uv
```

You also need a **Hedra API key** — sign-up instructions below.

---

## First-time setup

```bash
git clone <repo-url> delphi_ai_webcam
cd delphi_ai_webcam
uv sync                             # installs Python + deps into .venv/
cp .env.example .env                # then paste your Hedra key into .env
```

### Getting a Hedra API key

1. Sign up at [hedra.com](https://www.hedra.com).
2. Pick a plan from [hedra.com/pricing](https://www.hedra.com/pricing):
   - **Creator** ($30/mo, ~10 min of 720p generation) — fine for testing.
   - **Pro** ($75/mo, ~30 min of 720p generation) — baseline, but a single 60-min episode will exceed this; you'll pay overage credits on top.
   - **Enterprise** (custom pricing) — the right choice if you're running this weekly.
3. Open the dashboard → **API** / **Developers** section → create a key.
4. Paste it into `.env`:
   ```
   HEDRA_API_KEY=hk_live_xxxxxxxxxxxxxxxxx
   ```

---

## Usage

1. Drop a guest's webcam recording into `in/` (supports `.mp4`, `.mov`, `.mkv`, `.m4v`, `.webm`).
2. Drop a character portrait into `characters/` (`.png` or `.jpg`). Tips: 1024px+ portrait crop, face clearly visible, simple or transparent background works best.
3. Run:

   ```bash
   uv run delphi
   ```

4. Pick your character from the arrow-key menu.
5. Review the cost estimate. Type `y` to proceed, or anything else to abort.
6. Wait. For a 60-min episode expect roughly 15–40 minutes of wall time depending on concurrency and Hedra queue.
7. Output lands in `out/<input-name>_<character-name>.mp4`.

### Example

```bash
# Single run with defaults
uv run delphi

# Skip the prompt, cheaper resolution, specific character
uv run delphi --resolution 540p --character shakespeare --yes

# Higher concurrency for faster processing (respect Hedra rate limits)
uv run delphi --concurrency 6
```

### CLI flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--input PATH` | (prompt) | Video file to process; auto-picks if only one in `in/` |
| `--character NAME` | (prompt) | Character image stem (e.g. `shakespeare` for `characters/shakespeare.png`) |
| `--resolution 720p\|540p` | `720p` | Output resolution (540p is ~35% cheaper) |
| `--aspect 16:9\|9:16\|1:1` | `16:9` | Aspect ratio passed to Hedra |
| `--prompt TEXT` | `"talking head, natural expression, static body"` | Tone/mood hint for Hedra |
| `--concurrency N` | `4` | Max concurrent Hedra generations |
| `--yes` / `-y` | off | Skip the confirmation prompt |

---

## Cost

Hedra bills per second of generated video. This pipeline only sends speech to Hedra — silent gaps are rendered locally at zero cost.

For a **60-minute guest segment**, ~33% silence assumed (= 40 min of speech actually generated):

| Option | Cost/episode | Quality |
|--------|--------------|---------|
| **Hedra Character-3 @ 720p** (default) | **~$98** | Top tier — matches a16z |
| Hedra Character-3 @ 540p | ~$65 | Same motion quality, lower pixel resolution |
| fal.ai Fabric 1.0 @ 480p | ~$192 | Good lip-sync, less expressive motion |
| Replicate SadTalker | ~$5–10 | 2022-era quality, noticeably AI |
| Self-hosted Hallo2 | ~$2–5 | Good quality, high setup complexity |

See [docs/PLAN.md](docs/PLAN.md) for the full comparison and monthly projections.

Cost-reduction levers this pipeline gives you:

- **Silence trimming** eliminates ~33% of spend automatically.
- **Chunk cache** — re-rendering the same episode with a different character reuses unchanged chunks.
- **Cost preview prompt** forces explicit confirmation before any API calls.
- **`--resolution 540p`** cuts cost ~35% when 720p isn't needed.

---

## How it works

```
in/episode.mp4 ─┐
                ▼
      [1] Extract audio (ffmpeg)
                ▼
      [2] Detect silence → timeline of [speech], [silence], ...
                ▼
      [3] Split speech intervals >60s at internal pauses (Hedra's chunk limit)
                ▼
      [4] Preview cost, confirm [y/N]
                ▼
      [5] Submit speech chunks to Hedra in parallel
          Cache by (audio hash + image hash) — re-runs are free
                ▼
      [6] Render silence placeholders locally (still frame, matching FPS)
                ▼
      [7] Concatenate all clips in timeline order
                ▼
      [8] Mux the original audio back in (untouched)
                ▼
 out/episode_shakespeare.mp4
```

Everything is content-addressable by hash, so if a run fails halfway through you can just re-run it — previously-generated chunks are picked up from `.cache/chunks/`.

---

## Troubleshooting

**`Missing prerequisites: ffmpeg, ffprobe`**
Install ffmpeg (`brew install ffmpeg` / `winget install ffmpeg`) and re-run.

**`Missing HEDRA_API_KEY`**
Copy `.env.example` to `.env` and paste your Hedra key. The file must be in the project root (not inside `src/`).

**`VIRTUAL_ENV ... does not match the project environment path`**
Harmless warning — `uv` ignores the outer shell's virtualenv and uses the project's `.venv` automatically. You can suppress it with `unset VIRTUAL_ENV` in your shell before running `uv`.

**`generation ... errored: insufficient credits` (or similar)**
Your Hedra plan ran out of credits. Check your dashboard at hedra.com. Either wait for your plan to renew, top up with overage credits, or move to an Enterprise plan.

**`HARD-CUT N` in the job plan**
One or more speech segments exceed 60 seconds with no internal pauses ≥200ms to split at, so the pipeline cut them mid-speech. The seam can be noticeable — watch those spots in the output. Usually only happens with monologues or heavily compressed audio.

**Output looks glitchy at chunk boundaries**
Happens when Hedra returns a chunk at a different FPS than expected. The pipeline re-normalizes clips before concat; if it still glitches, open an issue with the offending audio chunk.

**Character image has odd framing / zoom**
Hedra works best with a face-centered portrait crop, ideally 1024px+ on the long side, clean background (transparent or solid). Full-body shots will be cropped or framed oddly.

**Ctrl-C mid-run**
Safe. Already-generated chunks stay in `.cache/chunks/` and are reused on the next run. You'll skip straight to the remaining work.

---

## Project layout

```
delphi_ai_webcam/
├── in/              # your webcam recordings (gitignored)
├── out/             # rendered avatar videos (gitignored)
├── characters/      # your custom illustrations (tracked in git)
├── docs/
│   └── PLAN.md      # full design doc, cost rationale, comparison
├── src/
│   ├── main.py      # CLI + orchestration
│   ├── audio.py     # audio extract, silence detect, chunking
│   ├── video.py     # still-frame render, concat, mux
│   ├── hedra.py     # async Hedra Character-3 client
│   ├── cache.py     # content-addressable chunk cache
│   └── config.py    # env, paths, constants
├── .cache/          # generated chunks (gitignored)
├── .env.example     # copy to .env and add your key
└── pyproject.toml   # uv project config
```
