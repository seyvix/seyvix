"""Telegram avatar proxy: fetches only from Telegram hosts, size-capped, image-sniffed, cached."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_AVATAR_BYTES = 1024 * 1024
MAX_REDIRECTS = 3
CACHE_TTL_SECONDS = 3600
CACHE_MAX_ENTRIES = 64
TELEGRAM_HOST_SUFFIXES = ("t.me", "telegram.org", "telesco.pe", "telegram-cdn.org")


@dataclass(frozen=True, slots=True)
class Avatar:
    content: bytes
    media_type: str


_cache: OrderedDict[str, tuple[float, Avatar | None]] = OrderedDict()


async def get_telegram_avatar(*, telegram_id: str, photo_url: str | None) -> Avatar | None:
    now = time.monotonic()
    cached = _cache.get(telegram_id)
    if cached is not None and cached[0] > now:
        _cache.move_to_end(telegram_id)
        return cached[1]
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
        avatar = await _fetch_image(client, photo_url) if photo_url else None
        if avatar is None:
            avatar = await _fetch_profile_photo(client, telegram_id=telegram_id)
    _cache[telegram_id] = (now + CACHE_TTL_SECONDS, avatar)
    _cache.move_to_end(telegram_id)
    while len(_cache) > CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)
    return avatar


def _allowed_hosts() -> tuple[str, ...]:
    api_host = urlsplit(get_settings().telegram_api_base).hostname
    return (*TELEGRAM_HOST_SUFFIXES, api_host) if api_host else TELEGRAM_HOST_SUFFIXES


def _host_allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    if parts.scheme not in {"https", "http"} or not host:
        return False
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _allowed_hosts())


def _sniff_image_type(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _fetch_image(client: httpx.AsyncClient, url: str) -> Avatar | None:
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not _host_allowed(current):
                logger.info("auth.avatar.host_rejected", host=urlsplit(current).hostname)
                return None
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    return None
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_AVATAR_BYTES:
                    return None
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_AVATAR_BYTES:
                        return None
                    chunks.append(chunk)
            content = b"".join(chunks)
            media_type = _sniff_image_type(content[:16])
            return Avatar(content=content, media_type=media_type) if media_type else None
    except httpx.HTTPError as exc:
        logger.info("auth.avatar.fetch_failed", error=type(exc).__name__)
    return None


async def _fetch_profile_photo(client: httpx.AsyncClient, *, telegram_id: str) -> Avatar | None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return None
    base = f"{settings.telegram_api_base.rstrip('/')}/bot{settings.telegram_bot_token}"
    try:
        photos = await client.get(
            f"{base}/getUserProfilePhotos",
            params={"user_id": telegram_id, "limit": 1},
        )
        photos.raise_for_status()
        file_id = _largest_photo_file_id(photos.json())
        if file_id is None:
            return None
        file_response = await client.get(f"{base}/getFile", params={"file_id": file_id})
        file_response.raise_for_status()
        file_payload = file_response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("auth.avatar.bot_api_failed", error=type(exc).__name__)
        return None
    result = file_payload.get("result") if isinstance(file_payload, dict) else None
    file_path = result.get("file_path") if isinstance(result, dict) else None
    if not isinstance(file_path, str) or not file_path:
        return None
    return await _fetch_image(
        client,
        f"{settings.telegram_api_base.rstrip('/')}/file/bot{settings.telegram_bot_token}/"
        f"{file_path.lstrip('/')}",
    )


def _largest_photo_file_id(payload: object) -> str | None:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    result = payload.get("result")
    photos = result.get("photos") if isinstance(result, dict) else None
    if not isinstance(photos, list) or not photos or not isinstance(photos[0], list):
        return None
    sizes = [
        size
        for size in photos[0]
        if isinstance(size, dict) and isinstance(size.get("file_id"), str)
    ]
    if not sizes:
        return None
    largest = max(
        sizes,
        key=lambda size: (
            int(size.get("file_size") or 0),
            int(size.get("width") or 0) * int(size.get("height") or 0),
        ),
    )
    return str(largest["file_id"])
