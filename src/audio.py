"""Audio extraction, silence detection, and speech chunking."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class Interval:
    start: float
    end: float
    kind: str  # "speech" | "silence"

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Chunk:
    index: int
    start: float
    end: float
    kind: str  # "speech" | "silence"
    hard_cut: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe_duration(media_path: Path) -> float:
    """Return media duration in seconds using ffprobe."""
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(media_path),
    ])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {media_path}: {result.stderr}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def extract_audio(video_path: Path, out_path: Path | None = None) -> Path:
    """Extract mono PCM WAV at AUDIO_SAMPLE_RATE for downstream processing."""
    if out_path is None:
        out_path = config.WORK_DIR / f"{video_path.stem}.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", str(config.AUDIO_SAMPLE_RATE),
        "-acodec", "pcm_s16le", str(out_path),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extract failed: {result.stderr}")
    return out_path


_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def detect_silence(
    audio_path: Path,
    threshold_db: int = config.SILENCE_THRESHOLD_DB,
    min_duration_s: float = config.SILENCE_MIN_DURATION_S,
) -> list[Interval]:
    """Return the full timeline as alternating speech / silence intervals."""
    total = probe_duration(audio_path)
    cmd = [
        "ffmpeg", "-nostats", "-loglevel", "info",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration_s}",
        "-f", "null", "-",
    ]
    result = _run(cmd)
    text = result.stderr

    silences: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in text.splitlines():
        m_start = _SILENCE_START_RE.search(line)
        if m_start:
            pending_start = float(m_start.group(1))
            continue
        m_end = _SILENCE_END_RE.search(line)
        if m_end and pending_start is not None:
            end = float(m_end.group(1))
            silences.append((max(0.0, pending_start), min(total, end)))
            pending_start = None
    if pending_start is not None:
        silences.append((pending_start, total))

    timeline: list[Interval] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor + 1e-3:
            timeline.append(Interval(cursor, s_start, "speech"))
        timeline.append(Interval(s_start, s_end, "silence"))
        cursor = s_end
    if cursor < total - 1e-3:
        timeline.append(Interval(cursor, total, "speech"))
    return timeline


def _find_internal_split(
    silences_within: list[tuple[float, float]],
    target: float,
) -> float | None:
    """Pick the silence closest to `target` for clean splitting.

    Returns the midpoint of the chosen silence, or None if no suitable
    silence exists (all too short).
    """
    suitable = [
        (s, e) for s, e in silences_within
        if (e - s) >= config.MIN_INTERNAL_SPLIT_SILENCE_S
    ]
    if not suitable:
        return None
    best = min(suitable, key=lambda se: abs(((se[0] + se[1]) / 2) - target))
    return (best[0] + best[1]) / 2


def chunk_timeline(
    timeline: list[Interval],
    audio_path: Path,
    max_s: int = config.MAX_CHUNK_SECONDS,
) -> list[Chunk]:
    """Break a timeline into Hedra-sized chunks.

    Speech intervals longer than `max_s` are split at internal micro-silences
    when possible, otherwise hard-cut. Silence intervals pass through as
    placeholders.
    """
    # Detect a looser silence pass for finding split points (micro-silences
    # down to 200ms that silencedetect with 1.5s min wouldn't catch).
    micro = _micro_silences(audio_path)

    chunks: list[Chunk] = []
    idx = 0
    for iv in timeline:
        if iv.kind == "silence":
            chunks.append(Chunk(idx, iv.start, iv.end, "silence"))
            idx += 1
            continue

        cursor = iv.start
        while iv.end - cursor > max_s:
            target = cursor + max_s - 1.0
            window = [
                (s, e) for s, e in micro
                if cursor + 5.0 < s and e < iv.end and s < cursor + max_s
            ]
            split_at = _find_internal_split(window, target)
            if split_at is None:
                split_at = cursor + max_s - config.HARD_CUT_SAFETY_S
                chunks.append(Chunk(idx, cursor, split_at, "speech", hard_cut=True))
            else:
                chunks.append(Chunk(idx, cursor, split_at, "speech"))
            idx += 1
            cursor = split_at

        if iv.end - cursor > 1e-3:
            chunks.append(Chunk(idx, cursor, iv.end, "speech"))
            idx += 1
    return chunks


def _micro_silences(audio_path: Path) -> list[tuple[float, float]]:
    """Detect short silences (>=200ms) for finer-grained splitting."""
    cmd = [
        "ffmpeg", "-nostats", "-loglevel", "info",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={config.SILENCE_THRESHOLD_DB}dB:d={config.MIN_INTERNAL_SPLIT_SILENCE_S}",
        "-f", "null", "-",
    ]
    result = _run(cmd)
    text = result.stderr
    out: list[tuple[float, float]] = []
    pending: float | None = None
    for line in text.splitlines():
        m_start = _SILENCE_START_RE.search(line)
        if m_start:
            pending = float(m_start.group(1))
            continue
        m_end = _SILENCE_END_RE.search(line)
        if m_end and pending is not None:
            out.append((pending, float(m_end.group(1))))
            pending = None
    return out


def cut_audio(audio_path: Path, start: float, end: float, out_path: Path) -> Path:
    """Extract a segment [start, end) to `out_path` as a mono WAV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(audio_path),
        "-ac", "1", "-ar", str(config.AUDIO_SAMPLE_RATE),
        "-acodec", "pcm_s16le", str(out_path),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut_audio failed: {result.stderr}")
    return out_path


def summarize(timeline: list[Interval]) -> tuple[float, float, float]:
    """Return (total_seconds, speech_seconds, silence_seconds)."""
    total = sum(iv.duration for iv in timeline)
    speech = sum(iv.duration for iv in timeline if iv.kind == "speech")
    silence = total - speech
    return total, speech, silence
