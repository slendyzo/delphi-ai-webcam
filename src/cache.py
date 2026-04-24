"""Content-addressable cache for Hedra outputs and silence placeholders."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import config


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def chunk_key(
    audio_path: Path,
    image_path: Path,
    resolution: str,
    aspect_ratio: str,
    prompt: str,
) -> str:
    h = hashlib.sha256()
    h.update(_hash_file(audio_path).encode())
    h.update(b"|")
    h.update(_hash_file(image_path).encode())
    h.update(b"|")
    h.update(resolution.encode())
    h.update(b"|")
    h.update(aspect_ratio.encode())
    h.update(b"|")
    h.update(prompt.encode())
    return h.hexdigest()


def chunk_path(key: str) -> Path:
    return config.CHUNK_CACHE_DIR / f"{key}.mp4"


def silence_key(
    image_path: Path,
    duration_s: float,
    fps: float,
    width: int,
    height: int,
) -> str:
    h = hashlib.sha256()
    h.update(_hash_file(image_path).encode())
    h.update(b"|")
    h.update(f"{duration_s:.6f}|{fps:.6f}|{width}x{height}".encode())
    return h.hexdigest()


def silence_path(key: str) -> Path:
    return config.SILENCE_CACHE_DIR / f"{key}.mp4"


def is_cached(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0
