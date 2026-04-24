"""Async Hedra Character-3 API client.

Flow (per live API at api.hedra.com/web-app/public):
    1. GET  /models                     -> pick Character-3 model_id
    2. POST /assets (image)             -> image_asset_id
       POST /assets/{id}/upload         -> upload image bytes
    3. POST /assets (audio)             -> audio_asset_id
       POST /assets/{id}/upload         -> upload audio bytes
    4. POST /generations                -> generation_id
    5. GET  /generations/{id}/status    -> poll
    6. GET  <url>                       -> download MP4

Auth header: x-api-key (lowercase).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from . import config


class HedraError(RuntimeError):
    pass


def _headers_json() -> dict[str, str]:
    if not config.HEDRA_API_KEY:
        raise HedraError(
            "HEDRA_API_KEY is empty. Copy .env.example to .env and paste your key."
        )
    return {"x-api-key": config.HEDRA_API_KEY, "Content-Type": "application/json"}


def _headers_raw() -> dict[str, str]:
    if not config.HEDRA_API_KEY:
        raise HedraError("HEDRA_API_KEY is empty.")
    return {"x-api-key": config.HEDRA_API_KEY}


_model_id_cache: str | None = None


async def get_character3_model_id(client: httpx.AsyncClient) -> str:
    """Resolve the Character-3 model id. Cached for the process lifetime."""
    global _model_id_cache
    if _model_id_cache:
        return _model_id_cache
    resp = await client.get(
        f"{config.HEDRA_API_BASE}/models", headers=_headers_json(),
    )
    if resp.status_code != 200:
        raise HedraError(f"list models failed: {resp.status_code} {resp.text}")
    models = resp.json()
    if not models:
        raise HedraError("no models returned from Hedra /models")

    preferred = None
    for m in models:
        name = (m.get("name") or m.get("display_name") or "").lower()
        if "character-3" in name or "character 3" in name or name == "character3":
            preferred = m
            break
    chosen = preferred or models[0]
    _model_id_cache = chosen["id"]
    return _model_id_cache


async def _create_asset(
    client: httpx.AsyncClient, name: str, kind: str,
) -> str:
    resp = await client.post(
        f"{config.HEDRA_API_BASE}/assets",
        headers=_headers_json(),
        json={"name": name, "type": kind},
    )
    if resp.status_code not in (200, 201):
        raise HedraError(
            f"create asset ({kind}) failed: {resp.status_code} {resp.text}"
        )
    return resp.json()["id"]


async def _upload_asset_bytes(
    client: httpx.AsyncClient,
    asset_id: str,
    path: Path,
    mime: str,
) -> None:
    with path.open("rb") as f:
        files = {"file": (path.name, f, mime)}
        resp = await client.post(
            f"{config.HEDRA_API_BASE}/assets/{asset_id}/upload",
            headers=_headers_raw(),
            files=files,
            timeout=120.0,
        )
    if resp.status_code not in (200, 201, 204):
        raise HedraError(
            f"upload asset {asset_id} failed: {resp.status_code} {resp.text}"
        )


async def upload_image(client: httpx.AsyncClient, image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    asset_id = await _create_asset(client, image_path.name, "image")
    await _upload_asset_bytes(client, asset_id, image_path, mime)
    return asset_id


async def upload_audio(client: httpx.AsyncClient, audio_path: Path) -> str:
    asset_id = await _create_asset(client, audio_path.name, "audio")
    await _upload_asset_bytes(client, asset_id, audio_path, "audio/wav")
    return asset_id


async def submit_generation(
    client: httpx.AsyncClient,
    model_id: str,
    image_asset_id: str,
    audio_asset_id: str,
    resolution: str,
    aspect_ratio: str,
    prompt: str,
) -> str:
    body = {
        "type": "video",
        "ai_model_id": model_id,
        "start_keyframe_id": image_asset_id,
        "audio_id": audio_asset_id,
        "generated_video_inputs": {
            "text_prompt": prompt,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        },
    }
    resp = await client.post(
        f"{config.HEDRA_API_BASE}/generations",
        headers=_headers_json(),
        json=body,
    )
    if resp.status_code not in (200, 201):
        raise HedraError(
            f"submit generation failed: {resp.status_code} {resp.text}"
        )
    return resp.json()["id"]


async def poll_until_done(
    client: httpx.AsyncClient,
    generation_id: str,
    timeout_s: float = config.HEDRA_GENERATION_TIMEOUT_S,
    interval_s: float = config.HEDRA_POLL_INTERVAL_S,
) -> str:
    """Poll status endpoint until complete; return the download URL."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while True:
        resp = await client.get(
            f"{config.HEDRA_API_BASE}/generations/{generation_id}/status",
            headers=_headers_json(),
        )
        if resp.status_code != 200:
            raise HedraError(
                f"poll {generation_id} failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        status = (data.get("status") or "").lower()
        if status == "complete":
            url = data.get("url")
            if not url:
                raise HedraError(f"generation {generation_id} complete but no url")
            return url
        if status == "error":
            raise HedraError(
                f"generation {generation_id} errored: "
                f"{data.get('error_message', 'unknown error')}"
            )
        if loop.time() >= deadline:
            raise HedraError(
                f"generation {generation_id} timed out after {timeout_s}s "
                f"(last status: {status})"
            )
        await asyncio.sleep(interval_s)


async def download_to(client: httpx.AsyncClient, url: str, dest: Path) -> Path:
    """Stream-download a video URL to disk."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    async with client.stream("GET", url, timeout=300.0) as resp:
        if resp.status_code != 200:
            raise HedraError(f"download failed: {resp.status_code}")
        with tmp.open("wb") as f:
            async for chunk in resp.aiter_bytes(1 << 16):
                f.write(chunk)
    tmp.replace(dest)
    return dest


_RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


async def generate_chunk(
    client: httpx.AsyncClient,
    image_path: Path,
    audio_path: Path,
    dest: Path,
    resolution: str,
    aspect_ratio: str,
    prompt: str,
    max_attempts: int = 3,
) -> Path:
    """End-to-end: upload → submit → poll → download, with retries."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            model_id = await get_character3_model_id(client)
            image_asset = await upload_image(client, image_path)
            audio_asset = await upload_audio(client, audio_path)
            gen_id = await submit_generation(
                client, model_id, image_asset, audio_asset,
                resolution, aspect_ratio, prompt,
            )
            url = await poll_until_done(client, gen_id)
            return await download_to(client, url, dest)
        except HedraError as exc:
            # Retry only on transient-looking errors.
            text = str(exc)
            transient = any(
                f"{code}" in text for code in _RETRY_STATUSES
            ) or "timed out" in text
            last_exc = exc
            if attempt == max_attempts or not transient:
                raise
            await asyncio.sleep(2 ** attempt)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise HedraError(f"network error after {attempt} attempts: {exc}")
            await asyncio.sleep(2 ** attempt)
    assert last_exc is not None
    raise last_exc


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60.0)
