"""Buffers Telegram messages into logical saves and uploads them to Seyvix.

* auto mode: messages arriving within `group_window_seconds` form one save (albums and quick
  series end up in one note);
* separate / manual mode: only albums (media groups) are buffered, for `media_group_seconds`.

Buckets keep only metadata (Telegram `file_id`s), never file bytes; attachments are downloaded
to a temporary directory at flush time and streamed to the backend in one request.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import InboundMaterial, SavedMaterial
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend, IngestItem, UploadFile

logger = logging.getLogger(__name__)


class FileTooLargeError(Exception):
    """Telegram refuses to hand this file to bots."""


class IngestReporter(Protocol):
    """Chat-side feedback for one save (implemented by the Telegram handler)."""

    async def loading(self, material: InboundMaterial) -> Any: ...

    async def saved(self, status: Any, saved: SavedMaterial, skipped: list[str]) -> None: ...

    async def nothing_saved(self, status: Any, skipped: list[str]) -> None: ...

    async def failed(self, status: Any, exc: Exception) -> None: ...


class FileFetcher(Protocol):
    async def enrich(self, material: InboundMaterial) -> InboundMaterial: ...

    async def download(self, file_id: str, destination: Path) -> None: ...


@dataclass(slots=True)
class _Bucket:
    reporter: IngestReporter
    materials: list[InboundMaterial]
    deadline: float
    status: asyncio.Task[Any]
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class TelegramIngestService:
    def __init__(
        self,
        *,
        backend: HttpSeyvixBackend,
        fetcher: FileFetcher,
        group_window_seconds: float,
        media_group_seconds: float,
        max_buffered_materials: int,
        max_download_bytes: int | None,
    ) -> None:
        self.backend = backend
        self.fetcher = fetcher
        self.group_window_seconds = group_window_seconds
        self.media_group_seconds = media_group_seconds
        self.max_buffered_materials = max_buffered_materials
        self.max_download_bytes = max_download_bytes
        self._buckets: dict[str, _Bucket] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def submit(
        self,
        material: InboundMaterial,
        *,
        mode: BotMode,
        reporter: IngestReporter,
    ) -> None:
        key, delay = self._buffering(material, mode)
        if key is None:
            status = await reporter.loading(material)
            self._spawn(self._save([material], reporter, status))
            return
        loop = asyncio.get_running_loop()
        bucket = self._buckets.get(key)
        if bucket is None:
            # Register before awaiting anything so concurrent updates join this bucket.
            bucket = _Bucket(
                reporter=reporter,
                materials=[material],
                deadline=loop.time() + delay,
                status=asyncio.create_task(reporter.loading(material)),
            )
            self._buckets[key] = bucket
            bucket.task = asyncio.create_task(self._run_bucket(key, bucket))
            self._tasks.add(bucket.task)
            bucket.task.add_done_callback(self._tasks.discard)
            return
        bucket.materials.append(material)
        full = len(bucket.materials) >= self.max_buffered_materials
        bucket.deadline = loop.time() if full else loop.time() + delay
        if full:
            # Start a fresh bucket for whatever arrives next.
            self._buckets.pop(key, None)
        bucket.wake.set()

    async def shutdown(self, grace_seconds: float = 30.0) -> None:
        """Flush buffered messages immediately and wait for in-flight saves."""
        loop = asyncio.get_running_loop()
        for bucket in self._buckets.values():
            bucket.deadline = loop.time()
            bucket.wake.set()
        if self._tasks:
            _, pending = await asyncio.wait(set(self._tasks), timeout=grace_seconds)
            for task in pending:
                task.cancel()

    def _spawn(self, coroutine: Awaitable[None]) -> None:
        task: asyncio.Task[None] = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _buffering(self, material: InboundMaterial, mode: BotMode) -> tuple[str | None, float]:
        group_id = material.source.group_id if material.source else None
        if mode == BotMode.AUTO:
            key = f"auto:{material.telegram_user_id}:{material.telegram_chat_id}"
            return key, self.group_window_seconds
        if group_id:
            return (
                f"album:{material.telegram_user_id}:{material.telegram_chat_id}:{group_id}",
                self.media_group_seconds,
            )
        return None, 0.0

    async def _run_bucket(self, key: str, bucket: _Bucket) -> None:
        loop = asyncio.get_running_loop()
        while (remaining := bucket.deadline - loop.time()) > 0:
            bucket.wake.clear()
            try:
                await asyncio.wait_for(bucket.wake.wait(), timeout=remaining)
            except TimeoutError:
                pass
        if self._buckets.get(key) is bucket:
            del self._buckets[key]
        try:
            status = await bucket.status
        except Exception:  # noqa: BLE001 - loading message failed; reporter sends a new one
            logger.warning("Could not send loading message", exc_info=True)
            status = None
        await self._save(bucket.materials, bucket.reporter, status)

    async def _save(
        self,
        materials: list[InboundMaterial],
        reporter: IngestReporter,
        status: Any,
    ) -> None:
        try:
            ordered = _deduplicate_repeated_captions(_sort_materials(materials))
            enriched = [await self.fetcher.enrich(material) for material in ordered]
            with tempfile.TemporaryDirectory(prefix="seyvix-bot-") as tmp:
                groups, files, skipped = await self._download(enriched, Path(tmp))
                if not groups:
                    await reporter.nothing_saved(status, skipped)
                    return
                first = enriched[0]
                saved = await self.backend.ingest(
                    telegram_user_id=int(first.telegram_user_id),
                    telegram_chat_id=first.telegram_chat_id,
                    groups=groups,
                    files=files,
                )
            logger.info(
                "Saved %s Telegram message(s) as %s (%s)", len(materials), saved.id, saved.status
            )
            await reporter.saved(status, saved, skipped)
        except Exception as exc:  # noqa: BLE001 - every failure is reported to the user
            logger.warning("Telegram save failed: %s", exc, exc_info=True)
            await _safely(reporter.failed(status, exc))

    async def _download(
        self,
        materials: list[InboundMaterial],
        directory: Path,
    ) -> tuple[list[list[IngestItem]], list[UploadFile], list[str]]:
        files: list[UploadFile] = []
        skipped: list[str] = []
        groups: list[list[IngestItem]] = []
        for group in _logical_groups(materials):
            items: list[IngestItem] = []
            for material in group:
                attachment = material.attachment
                if attachment is None:
                    items.append(IngestItem(material=material, file_index=None))
                    continue
                too_large = (
                    self.max_download_bytes is not None
                    and attachment.file_size is not None
                    and attachment.file_size > self.max_download_bytes
                )
                path = directory / f"{len(files)}"
                try:
                    if too_large:
                        raise FileTooLargeError(attachment.filename)
                    await self.fetcher.download(attachment.file_id, path)
                except FileTooLargeError:
                    skipped.append(attachment.filename)
                    if material.caption or material.text:
                        # Keep the text of the message even if its file cannot be fetched.
                        items.append(
                            IngestItem(
                                material=replace(material, attachment=None),
                                file_index=None,
                            )
                        )
                    continue
                files.append(
                    UploadFile(
                        path=path,
                        filename=attachment.filename,
                        mime_type=attachment.mime_type,
                    )
                )
                items.append(IngestItem(material=material, file_index=len(files) - 1))
            if items:
                groups.append(items)
        return groups, files, skipped


async def _safely(awaitable: Awaitable[None]) -> None:
    try:
        await awaitable
    except Exception:  # noqa: BLE001 - feedback is best effort (message deleted, bot blocked)
        logger.warning("Could not deliver save feedback", exc_info=True)


def _sort_materials(materials: list[InboundMaterial]) -> list[InboundMaterial]:
    return sorted(materials, key=lambda item: _message_id_sort_key(item.telegram_message_id))


def _message_id_sort_key(value: str) -> tuple[int, str]:
    return (int(value), value) if value.isdecimal() else (0, value)


def _deduplicate_repeated_captions(materials: list[InboundMaterial]) -> list[InboundMaterial]:
    seen: set[str] = set()
    result: list[InboundMaterial] = []
    for material in materials:
        caption = material.caption.strip() if material.caption else None
        if caption and caption in seen:
            result.append(replace(material, caption=None))
            continue
        if caption:
            seen.add(caption)
        result.append(material)
    return result


def _logical_groups(materials: list[InboundMaterial]) -> list[list[InboundMaterial]]:
    """One group per Telegram message, except albums which form a single group."""
    groups: dict[str, list[InboundMaterial]] = {}
    for material in materials:
        if material.source is not None and material.source.group_id:
            key = f"group:{material.telegram_chat_id}:{material.source.group_id}"
        else:
            key = f"message:{material.telegram_chat_id}:{material.telegram_message_id}"
        groups.setdefault(key, []).append(material)
    return list(groups.values())
