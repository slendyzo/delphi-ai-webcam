# Delphi AI Webcam

Animate a custom illustration to lip-sync with a webcam recording, for anonymous podcast guests. Matches the avatar pattern the a16z Show uses when guests like signüll appear pseudonymously.

Drop a webcam recording into `in/`, pick a character from `characters/`, run one command, and a lip-synced MP4 lands in `out/` — same duration, same audio, same frame count as the input. Silent gaps hold a still frame so you only pay for AI where the guest is actually speaking.

Uses [Hedra Character-3](https://www.hedra.com) for the animation. See [docs/PLAN.md](docs/PLAN.md) for full design rationale.

---

## The 60-second version

There are two scripts you'll ever double-click:

| File | What it does | When to use |
|------|--------------|-------------|
| `install.command` (Mac) / `install.bat` (Windows) | Installs ffmpeg, uv, Python deps; creates `.env` and asks for your Hedra key | Once, when you clone the repo or move to a new machine |
| `run.command` (Mac) / `run.bat` (Windows) | Runs the animation pipeline | Every time you want to process a video |

Typical flow: run the installer once. Then each episode, drop the webcam file in `in/`, drop the character illustration in `characters/`, double-click `run.command`, answer the menus, walk away.

---

## First-time setup

### The one-click way (recommended)

1. Clone the repo and open the folder in Finder (Mac) or Explorer (Windows).
2. Double-click **`install.command`** (Mac) or **`install.bat`** (Windows).
3. Follow the prompts. When it asks, paste your Hedra API key (see below for how to get one).

The installer is idempotent — run it again any time to re-sync after pulling updates.

### Getting a Hedra API key

1. Sign up at [hedra.com](https://www.hedra.com) and subscribe to at least the **Creator** plan. API access is gated behind a paid plan.
   - **Creator** (~$24–30/mo, ~10 min of 720p generation) — fine for testing.
   - **Pro** (~$60–75/mo, ~30 min of 720p) — baseline, but a single 60-min episode exceeds this; overage credits apply.
   - **Enterprise** (custom) — the right plan for a weekly podcast cadence.
2. Open [hedra.com/api-profile](https://www.hedra.com/api-profile) and create a key.
3. When the installer prompts you, paste it. It gets saved to `.env` (gitignored).

### The manual way (for power users)

```bash
# Mac
brew install ffmpeg uv

# Windows
winget install ffmpeg astral-sh.uv
```

```bash
uv sync
cp .env.example .env       # then edit .env and paste your Hedra key
```

---

## Usage

1. Drop a guest's webcam recording into `in/` (supports `.mp4`, `.mov`, `.mkv`, `.m4v`, `.webm`).
2. Drop a character portrait into `characters/` (`.png` or `.jpg`). Tips: 1024px+ portrait crop, face clearly visible, simple or transparent background works best. **Human face proportions animate best** — muppets and non-human geometry produce weak lip motion.
3. Double-click **`run.command`** (Mac) or **`run.bat`** (Windows). A terminal opens and asks:
   - Which character?
   - Resolution? (540p cheap / 720p recommended / 1080p premium — credit cost shown)
   - Aspect ratio? (16:9 / 1:1 / 9:16)
4. Review the job plan with cost estimate. Type `y` to proceed.
5. Wait. Hedra takes ~2 minutes per chunk of output — a 10-second clip takes about 2 minutes, a 60-minute episode 15–40 minutes depending on concurrency and queue.
6. Output lands in `out/<input-name>_<character-name>.mp4`.

**Important:** Progress sitting at `0/1` for a minute or two is normal — that's the Hedra queue, not a hang. Don't Ctrl-C early unless you really mean it.

### Command-line version

If you prefer the terminal:
```bash
uv run delphi
```

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
| `--resolution 540p\|720p\|1080p` | `720p` | Output resolution. 540p costs half of 720p (3 credits/sec vs 6); 1080p costs 1.6× (9.6 credits/sec). |
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
