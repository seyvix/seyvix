from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import (
    Attachment,
    InboundMaterial,
    MaterialType,
    SavedMaterial,
    SourceMetadata,
)
from telegram_bot.infrastructure.backend_client import BackendUnavailableError
from telegram_bot.services.ingest import FileTooLargeError, TelegramIngestService


@dataclass
class FakeBackend:
    calls: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None

    async def ingest(self, **kwargs: Any) -> SavedMaterial:
        files = kwargs["files"]
        kwargs["file_bytes"] = [file.path.read_bytes() for file in files]
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SavedMaterial(title="Note", id="n1", status="saved")


class FakeFetcher:
    def __init__(self, too_large: set[str] | None = None) -> None:
        self.too_large = too_large or set()

    async def enrich(self, material: InboundMaterial) -> InboundMaterial:
        return material

    async def download(self, file_id: str, destination: Path) -> None:
        if file_id in self.too_large:
            raise FileTooLargeError(file_id)
        destination.write_bytes(file_id.encode())  # noqa: ASYNC240 - tiny test fixture


@dataclass
class FakeReporter:
    events: list[tuple[str, Any]] = field(default_factory=list)

    async def loading(self, material: InboundMaterial) -> str:
        self.events.append(("loading", material.telegram_message_id))
        return "status"

    async def saved(self, status: Any, saved: SavedMaterial, skipped: list[str]) -> None:
        self.events.append(("saved", skipped))

    async def nothing_saved(self, status: Any, skipped: list[str]) -> None:
        self.events.append(("nothing", skipped))

    async def failed(self, status: Any, exc: Exception) -> None:
        self.events.append(("failed", type(exc).__name__))


def _material(
    message_id: str,
    *,
    file_id: str | None = None,
    file_size: int | None = None,
    group_id: str | None = None,
    caption: str | None = None,
) -> InboundMaterial:
    return InboundMaterial(
        telegram_user_id="42",
        telegram_chat_id="42",
        telegram_message_id=message_id,
        message_date=1_700_000_000,
        material_type=MaterialType.PHOTO if file_id else MaterialType.TEXT,
        text=None if file_id else f"text {message_id}",
        caption=caption,
        attachment=(
            Attachment(
                file_id=file_id,
                filename=f"{file_id}.jpg",
                mime_type="image/jpeg",
                file_size=file_size,
            )
            if file_id
            else None
        ),
        source=SourceMetadata(
            provider="telegram",
            provider_label="Telegram",
            external_id=f"42:{message_id}",
            group_id=group_id,
        ),
    )


def _service(backend: FakeBackend, fetcher: FakeFetcher | None = None) -> TelegramIngestService:
    return TelegramIngestService(
        backend=backend,  # type: ignore[arg-type]
        fetcher=fetcher or FakeFetcher(),
        group_window_seconds=0.05,
        media_group_seconds=0.05,
        max_buffered_materials=3,
        max_download_bytes=1000,
    )


def test_auto_mode_buffers_a_quick_series_into_one_request() -> None:
    backend, reporter = FakeBackend(), FakeReporter()

    async def scenario() -> None:
        service = _service(backend)
        await service.submit(
            _material("2", file_id="b", group_id="g"), mode=BotMode.AUTO, reporter=reporter
        )
        await service.submit(
            _material("1", file_id="a", group_id="g"), mode=BotMode.AUTO, reporter=reporter
        )
        await service.submit(_material("3"), mode=BotMode.AUTO, reporter=reporter)
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert len(backend.calls) == 1
    groups = backend.calls[0]["groups"]
    # Album (sorted by message id) is one group, the text message another.
    assert [[item.material.telegram_message_id for item in g] for g in groups] == [
        ["1", "2"],
        ["3"],
    ]
    assert backend.calls[0]["file_bytes"] == [b"a", b"b"]
    assert reporter.events[0] == ("loading", "2")
    assert reporter.events[-1] == ("saved", [])


def test_separate_mode_saves_single_messages_immediately() -> None:
    backend, reporter = FakeBackend(), FakeReporter()

    async def scenario() -> None:
        service = _service(backend)
        await service.submit(_material("1"), mode=BotMode.SEPARATE, reporter=reporter)
        await service.submit(_material("2"), mode=BotMode.SEPARATE, reporter=reporter)
        await service.shutdown()

    asyncio.run(scenario())
    assert len(backend.calls) == 2


def test_full_bucket_flushes_early_and_shutdown_flushes_rest() -> None:
    backend, reporter = FakeBackend(), FakeReporter()

    async def scenario() -> None:
        service = TelegramIngestService(
            backend=backend,  # type: ignore[arg-type]
            fetcher=FakeFetcher(),
            group_window_seconds=60,
            media_group_seconds=60,
            max_buffered_materials=2,
            max_download_bytes=None,
        )
        for message_id in ("1", "2", "3"):
            await service.submit(_material(message_id), mode=BotMode.AUTO, reporter=reporter)
        await service.shutdown(grace_seconds=5)

    asyncio.run(scenario())
    assert [len(call["groups"]) for call in backend.calls] == [2, 1]


def test_files_over_telegram_limit_are_skipped_but_caption_kept() -> None:
    backend, reporter = FakeBackend(), FakeReporter()

    async def scenario() -> None:
        service = _service(backend, FakeFetcher(too_large={"api-says-big"}))
        await service.submit(
            _material("1", file_id="huge", file_size=5000, caption="look"),
            mode=BotMode.SEPARATE,
            reporter=reporter,
        )
        await service.submit(
            _material("2", file_id="api-says-big"),
            mode=BotMode.SEPARATE,
            reporter=reporter,
        )
        await service.shutdown()

    asyncio.run(scenario())
    assert len(backend.calls) == 1
    item = backend.calls[0]["groups"][0][0]
    assert item.material.attachment is None and item.file_index is None
    assert ("saved", ["huge.jpg"]) in reporter.events
    assert ("nothing", ["api-says-big.jpg"]) in reporter.events


def test_backend_outage_is_reported_to_the_user() -> None:
    backend = FakeBackend(error=BackendUnavailableError("down"))
    reporter = FakeReporter()

    async def scenario() -> None:
        service = _service(backend)
        await service.submit(_material("1"), mode=BotMode.SEPARATE, reporter=reporter)
        await service.shutdown()

    asyncio.run(scenario())
    assert reporter.events[-1] == ("failed", "BackendUnavailableError")
