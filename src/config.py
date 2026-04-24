"""Central configuration: paths, constants, environment."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

IN_DIR = PROJECT_ROOT / "in"
OUT_DIR = PROJECT_ROOT / "out"
CHARACTERS_DIR = PROJECT_ROOT / "characters"
DOCS_DIR = PROJECT_ROOT / "docs"
CACHE_DIR = PROJECT_ROOT / ".cache"
CHUNK_CACHE_DIR = CACHE_DIR / "chunks"
SILENCE_CACHE_DIR = CACHE_DIR / "silence"
WORK_DIR = CACHE_DIR / "work"

HEDRA_API_BASE = "https://api.hedra.com/web-app/public"
HEDRA_API_KEY = os.environ.get("HEDRA_API_KEY", "").strip()
HEDRA_MAX_CONCURRENT = int(os.environ.get("HEDRA_MAX_CONCURRENT", "4"))
HEDRA_POLL_INTERVAL_S = 5
HEDRA_GENERATION_TIMEOUT_S = 600
HEDRA_DEFAULT_PROMPT = "talking head, natural expression, static body"

MAX_CHUNK_SECONDS = 60
HARD_CUT_SAFETY_S = 0.5

RESOLUTIONS = ("720p", "540p")
DEFAULT_RESOLUTION = "720p"

CREDITS_PER_SEC = {"720p": 6, "540p": 4}
CREDIT_USD_RATE = 0.0068

ASPECT_RATIOS = ("16:9", "9:16", "1:1")
DEFAULT_ASPECT_RATIO = "16:9"

SILENCE_THRESHOLD_DB = -30
SILENCE_MIN_DURATION_S = 1.5
MIN_INTERNAL_SPLIT_SILENCE_S = 0.2
AUDIO_SAMPLE_RATE = 24000

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".m4v", ".webm")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def ensure_dirs() -> None:
    """Create all project folders if missing. Safe to call repeatedly."""
    for path in (IN_DIR, OUT_DIR, CHARACTERS_DIR, DOCS_DIR, CACHE_DIR,
                 CHUNK_CACHE_DIR, SILENCE_CACHE_DIR, WORK_DIR):
        path.mkdir(parents=True, exist_ok=True)


def estimate_credits(speech_seconds: float, resolution: str) -> int:
    return int(round(speech_seconds * CREDITS_PER_SEC[resolution]))


def estimate_usd(credits: int) -> float:
    return credits * CREDIT_USD_RATE
