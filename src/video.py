"""Video assembly: still-frame placeholders, concat, and final mux."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


RESOLUTION_DIMS = {
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "540p": (960, 540),
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe_fps(video_path: Path) -> float:
    """Return the video's average frame rate."""
    result = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate",
        "-of", "json", str(video_path),
    ])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe fps failed: {result.stderr}")
    data = json.loads(result.stdout)
    rate = data["streams"][0]["avg_frame_rate"]
    if "/" in rate:
        num, den = rate.split("/")
        if int(den) == 0:
            raise RuntimeError(f"invalid fps {rate} in {video_path}")
        return int(num) / int(den)
    return float(rate)


def probe_resolution(video_path: Path) -> tuple[int, int]:
    result = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(video_path),
    ])
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe res failed: {result.stderr}")
    data = json.loads(result.stdout)
    s = data["streams"][0]
    return int(s["width"]), int(s["height"])


def render_silence_placeholder(
    image: Path,
    duration: float,
    fps: float,
    size: tuple[int, int],
    out: Path,
) -> Path:
    """Render a silent video clip of the static image at given duration/fps/size.

    Uses the same pixel format and codec as Hedra outputs (yuv420p, libx264)
    so the concat demuxer can stitch without re-encoding.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", f"{fps}",
        "-t", f"{duration:.3f}",
        "-i", str(image),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-r", f"{fps}",
        "-an", str(out),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg silence render failed: {result.stderr}")
    return out


def _matches(video_path: Path, fps: float, size: tuple[int, int]) -> bool:
    """Check if a clip already matches target params (±1px, ±0.01fps)."""
    try:
        w, h = probe_resolution(video_path)
        f = probe_fps(video_path)
    except Exception:
        return False
    return abs(w - size[0]) <= 1 and abs(h - size[1]) <= 1 and abs(f - fps) < 0.05


def normalize_clip(
    video_path: Path,
    fps: float,
    size: tuple[int, int],
    out: Path,
) -> Path:
    """Re-encode a clip to matching fps/size/codec so concat is seamless."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if _matches(video_path, fps, size):
        # Strip audio and re-wrap without re-encoding video.
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-c:v", "copy", "-an", str(out),
        ]
        result = _run(cmd)
        if result.returncode == 0:
            return out

    width, height = size
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-r", f"{fps}",
        "-an", str(out),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed: {result.stderr}")
    return out


def concat_clips(clips: list[Path], out: Path) -> Path:
    """Concatenate clips (all must share codec/fps/resolution) into `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    concat_file = out.parent / f"{out.stem}.concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{str(c.resolve())}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy", str(out),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr}")
    return out


def mux_original_audio(
    stitched_video: Path,
    original_audio: Path,
    out: Path,
) -> Path:
    """Muxes the stitched silent video with the pristine original audio track."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(stitched_video),
        "-i", str(original_audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out),
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {result.stderr}")
    return out
