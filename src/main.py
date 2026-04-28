"""Delphi AI Webcam — CLI entry point.

Usage:
    uv run delphi
    uv run delphi --resolution 540p --character shakespeare
    uv run delphi --yes                         # skip confirmation
    uv run delphi --aspect 16:9 --concurrency 4
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from . import audio, cache, config, hedra, video

console = Console()


def _check_prereqs() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        console.print(
            f"[red]Missing prerequisites:[/red] {', '.join(missing)}.\n"
            "Install with: [cyan]brew install ffmpeg[/cyan] (Mac) "
            "or [cyan]winget install ffmpeg[/cyan] (Windows)."
        )
        sys.exit(1)
    if not config.HEDRA_API_KEY:
        console.print(
            "[red]Missing HEDRA_API_KEY.[/red] Copy [cyan].env.example[/cyan] to "
            "[cyan].env[/cyan] and paste your key. See README for signup."
        )
        sys.exit(1)


def _pick_input_video(explicit: Path | None) -> Path:
    if explicit:
        if not explicit.exists():
            console.print(f"[red]Input video not found:[/red] {explicit}")
            sys.exit(1)
        return explicit

    videos = sorted(
        p for p in config.IN_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS
    )
    if not videos:
        console.print(
            f"[red]No videos in[/red] {config.IN_DIR}. "
            f"Drop a file with one of: {', '.join(config.VIDEO_EXTENSIONS)}"
        )
        sys.exit(1)
    if len(videos) == 1:
        return videos[0]

    choice = questionary.select(
        "Multiple videos found in in/ — pick one:",
        choices=[str(v.name) for v in videos],
    ).ask()
    if choice is None:
        sys.exit(130)
    return config.IN_DIR / choice


def _pick_resolution(explicit: str | None) -> str:
    if explicit:
        return explicit
    hints = {
        "540p": "3 credits/sec — cheapest, good for drafts",
        "720p": "6 credits/sec — recommended, matches a16z Show",
        "1080p": "9.6 credits/sec — premium, for final masters",
    }
    choices = [
        questionary.Choice(f"{r}  ({hints[r]})", value=r)
        for r in config.RESOLUTIONS
    ]
    choice = questionary.select(
        "Output resolution?",
        choices=choices,
        default=next(c for c in choices if c.value == config.DEFAULT_RESOLUTION),
    ).ask()
    if choice is None:
        sys.exit(130)
    return choice


def _pick_aspect(explicit: str | None) -> str:
    if explicit:
        return explicit
    hints = {
        "16:9": "landscape — most podcasts, widescreen edits",
        "1:1": "square — social clips, Instagram feed",
        "9:16": "vertical — Shorts, Reels, TikTok",
    }
    choices = [
        questionary.Choice(f"{a}  ({hints[a]})", value=a)
        for a in config.ASPECT_RATIOS
    ]
    choice = questionary.select(
        "Output aspect ratio?",
        choices=choices,
        default=next(c for c in choices if c.value == config.DEFAULT_ASPECT_RATIO),
    ).ask()
    if choice is None:
        sys.exit(130)
    return choice


def _pick_prompt(explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    answer = questionary.text(
        "Prompt (tone/mood hint sent to Hedra):",
        default=config.HEDRA_DEFAULT_PROMPT,
    ).ask()
    if answer is None:
        sys.exit(130)
    answer = answer.strip()
    return answer or config.HEDRA_DEFAULT_PROMPT


def _pick_character(explicit: str | None) -> Path:
    images = sorted(
        p for p in config.CHARACTERS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in config.IMAGE_EXTENSIONS
    )
    if not images:
        console.print(
            f"[red]No character illustrations in[/red] {config.CHARACTERS_DIR}. "
            f"Drop a portrait image ({', '.join(config.IMAGE_EXTENSIONS)})."
        )
        sys.exit(1)

    if explicit:
        for img in images:
            if img.stem == explicit or img.name == explicit:
                return img
        console.print(
            f"[red]Character '{explicit}' not found in[/red] {config.CHARACTERS_DIR}. "
            f"Available: {', '.join(i.stem for i in images)}"
        )
        sys.exit(1)

    if len(images) == 1:
        return images[0]

    choice = questionary.select(
        "Pick a character:",
        choices=[img.name for img in images],
    ).ask()
    if choice is None:
        sys.exit(130)
    return config.CHARACTERS_DIR / choice


async def _process_speech_chunk(
    client: hedra.httpx.AsyncClient,
    audio_path: Path,
    chunk: audio.Chunk,
    image_path: Path,
    resolution: str,
    aspect_ratio: str,
    prompt: str,
    sem: asyncio.Semaphore,
    progress: Progress,
    task_id: int,
) -> Path:
    work_audio = config.WORK_DIR / f"chunk_{chunk.index:04d}.wav"
    audio.cut_audio(audio_path, chunk.start, chunk.end, work_audio)

    key = cache.chunk_key(work_audio, image_path, resolution, aspect_ratio, prompt)
    dest = cache.chunk_path(key)
    if cache.is_cached(dest):
        progress.advance(task_id)
        return dest

    async with sem:
        out = await hedra.generate_chunk(
            client, image_path, work_audio, dest,
            resolution=resolution, aspect_ratio=aspect_ratio, prompt=prompt,
        )
    progress.advance(task_id)
    return out


def _render_silence_chunk(
    chunk: audio.Chunk,
    image_path: Path,
    fps: float,
    size: tuple[int, int],
) -> Path:
    key = cache.silence_key(image_path, chunk.duration, fps, size[0], size[1])
    dest = cache.silence_path(key)
    if cache.is_cached(dest):
        return dest
    return video.render_silence_placeholder(image_path, chunk.duration, fps, size, dest)


def _print_summary(
    input_video: Path,
    character: Path,
    resolution: str,
    aspect_ratio: str,
    prompt: str,
    timeline: list[audio.Interval],
    chunks: list[audio.Chunk],
) -> None:
    total, speech, silence = audio.summarize(timeline)
    speech_chunks = [c for c in chunks if c.kind == "speech"]
    silence_chunks = [c for c in chunks if c.kind == "silence"]
    hard_cuts = sum(1 for c in speech_chunks if c.hard_cut)

    credits = config.estimate_credits(speech, resolution)
    usd = config.estimate_usd(credits)

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Input", str(input_video.relative_to(config.PROJECT_ROOT)))
    table.add_row("Character", character.name)
    table.add_row("Resolution", resolution)
    table.add_row("Aspect", aspect_ratio)
    table.add_row("Prompt", f'"{prompt}"')
    table.add_row("Duration", f"{_fmt_time(total)}")
    table.add_row("Speech / Silence", f"{speech / total:.0%} / {silence / total:.0%}")
    table.add_row("Speech chunks", f"{len(speech_chunks)} (each ≤ {config.MAX_CHUNK_SECONDS}s)")
    table.add_row("Silence segments", f"{len(silence_chunks)} (rendered locally, no AI cost)")
    if hard_cuts:
        table.add_row(
            "[yellow]Hard cuts[/yellow]",
            f"{hard_cuts} (monologue longer than {config.MAX_CHUNK_SECONDS}s with no internal pause)",
        )
    table.add_row(
        "[bold]Estimated cost[/bold]",
        f"[bold]~${usd:.2f}[/bold] ({credits:,} credits)",
    )
    console.print(Panel(table, title="[bold]Job plan[/bold]", border_style="cyan"))


def _fmt_time(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


async def _run_pipeline(
    input_video: Path,
    character: Path,
    resolution: str,
    aspect_ratio: str,
    prompt: str,
    assume_yes: bool,
    concurrency: int,
) -> Path:
    console.print(f"[dim]Extracting audio from[/dim] {input_video.name} ...")
    original_audio = audio.extract_audio(input_video)

    console.print("[dim]Detecting silence ...[/dim]")
    timeline = audio.detect_silence(original_audio)
    chunks = audio.chunk_timeline(timeline, original_audio)

    _print_summary(input_video, character, resolution, aspect_ratio, prompt, timeline, chunks)

    if not assume_yes:
        if not await questionary.confirm("Proceed?", default=False).ask_async():
            console.print("[yellow]Aborted.[/yellow]")
            sys.exit(0)

    speech_chunks = [c for c in chunks if c.kind == "speech"]
    silence_chunks = [c for c in chunks if c.kind == "silence"]

    sem = asyncio.Semaphore(concurrency)
    progress_columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ]

    speech_outputs: dict[int, Path] = {}
    async with hedra.make_client() as client:
        with Progress(*progress_columns, console=console, transient=False) as progress:
            task = progress.add_task(
                "[cyan]Hedra chunks[/cyan]", total=len(speech_chunks),
            )
            results = await asyncio.gather(*[
                _process_speech_chunk(
                    client, original_audio, c, character,
                    resolution, aspect_ratio, prompt,
                    sem, progress, task,
                )
                for c in speech_chunks
            ])
            for chunk, path in zip(speech_chunks, results):
                speech_outputs[chunk.index] = path

    # Determine canonical fps + size from the first Hedra output.
    size = video.RESOLUTION_DIMS[resolution]
    if speech_chunks:
        first_out = speech_outputs[speech_chunks[0].index]
        target_fps = video.probe_fps(first_out)
    else:
        target_fps = 25.0

    console.print(f"[dim]Rendering {len(silence_chunks)} silence segments at {target_fps:.2f} fps ...[/dim]")
    silence_outputs: dict[int, Path] = {}
    for c in silence_chunks:
        silence_outputs[c.index] = _render_silence_chunk(c, character, target_fps, size)

    # Normalize every clip to identical codec/fps/size so concat is seamless.
    normalized: list[Path] = []
    with Progress(*progress_columns, console=console, transient=True) as progress:
        task = progress.add_task(
            "[cyan]Normalizing clips[/cyan]", total=len(chunks),
        )
        for c in chunks:
            raw = speech_outputs[c.index] if c.kind == "speech" else silence_outputs[c.index]
            norm = config.WORK_DIR / f"norm_{c.index:04d}.mp4"
            video.normalize_clip(raw, target_fps, size, norm)
            normalized.append(norm)
            progress.advance(task)

    console.print("[dim]Stitching ...[/dim]")
    stitched = config.WORK_DIR / f"{input_video.stem}_stitched.mp4"
    video.concat_clips(normalized, stitched)

    out_name = f"{input_video.stem}_{character.stem}.mp4"
    final_out = config.OUT_DIR / out_name
    console.print("[dim]Muxing original audio ...[/dim]")
    video.mux_original_audio(stitched, original_audio, final_out)

    return final_out


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="delphi",
        description="Animate a character illustration to lip-sync with a webcam recording.",
    )
    parser.add_argument("--input", type=Path, help="Input video path (default: pick from in/)")
    parser.add_argument("--character", type=str, help="Character image stem (default: prompt)")
    parser.add_argument(
        "--resolution", choices=config.RESOLUTIONS, default=None,
        help=f"Output resolution. If omitted, you'll be asked. Default via --yes: {config.DEFAULT_RESOLUTION}.",
    )
    parser.add_argument(
        "--aspect", choices=config.ASPECT_RATIOS, default=None,
        help=f"Aspect ratio. If omitted, you'll be asked. Default via --yes: {config.DEFAULT_ASPECT_RATIO}.",
    )
    parser.add_argument(
        "--prompt", type=str, default=None,
        help=f"Text prompt sent to Hedra (tone/mood hint). If omitted, you'll be asked. Default via --yes: \"{config.HEDRA_DEFAULT_PROMPT}\".",
    )
    parser.add_argument(
        "--concurrency", type=int, default=config.HEDRA_MAX_CONCURRENT,
        help="Max concurrent Hedra generations.",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt.")
    args = parser.parse_args()

    _check_prereqs()
    config.ensure_dirs()

    input_video = _pick_input_video(args.input)
    character = _pick_character(args.character)
    if args.yes:
        resolution = args.resolution or config.DEFAULT_RESOLUTION
        aspect = args.aspect or config.DEFAULT_ASPECT_RATIO
        prompt = args.prompt if args.prompt is not None else config.HEDRA_DEFAULT_PROMPT
    else:
        resolution = _pick_resolution(args.resolution)
        aspect = _pick_aspect(args.aspect)
        prompt = _pick_prompt(args.prompt)

    try:
        final_out = asyncio.run(_run_pipeline(
            input_video=input_video,
            character=character,
            resolution=resolution,
            aspect_ratio=aspect,
            prompt=prompt,
            assume_yes=args.yes,
            concurrency=max(1, args.concurrency),
        ))
    except hedra.HedraError as exc:
        console.print(f"[red]Hedra error:[/red] {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Cached chunks are preserved — re-run to resume.[/yellow]")
        sys.exit(130)

    console.print(f"\n[green]✓ Done →[/green] {final_out}")


if __name__ == "__main__":
    main()
