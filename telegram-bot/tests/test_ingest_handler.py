from __future__ import annotations

import asyncio

from telegram_bot.domain.models import UserContext
from telegram_bot.handlers.ingest import _download_error_text, ingest_handler
from telegram_bot.texts.common import DOWNLOAD_FAILED, FILE_TOO_LARGE


class FakeStatusMessage:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    async def edit_text(self, text: str, **_: object) -> None:
        self.events.append(("edit", text))


class FakeMessage:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    def model_dump(self, **_: object) -> dict[str, object]:
        return {
            "message_id": 10,
            "date": 1_777_777_777,
            "chat": {"id": 700, "type": "private"},
            "from": {"id": 100500, "is_bot": False, "first_name": "User"},
            "document": {
                "file_id": "too-large-file",
                "file_name": "huge.bin",
                "mime_type": "application/octet-stream",
            },
        }

    async def reply(self, text: str, **_: object) -> FakeStatusMessage:
        self.events.append(("reply", text))
        return FakeStatusMessage(self.events)

    async def answer(self, text: str, **_: object) -> None:
        self.events.append(("answer", text))


class FakeBot:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    async def download(self, file_id: str, **_: object) -> None:
        self.events.append(("download", file_id))
        raise RuntimeError("Telegram refused file download")


class UnusedModeService:
    async def get_state(self, telegram_user_id: str) -> object:
        raise AssertionError("state is not needed when download fails")


class UnusedIngestService:
    async def ingest(self, **_: object) -> None:
        raise AssertionError("ingest is not called when download fails")


def test_ingest_handler_replies_with_loading_before_downloading_attachment() -> None:
    async def scenario() -> None:
        events: list[tuple[str, str]] = []

        await ingest_handler(
            FakeMessage(events),  # type: ignore[arg-type]
            FakeBot(events),  # type: ignore[arg-type]
            UnusedModeService(),  # type: ignore[arg-type]
            UnusedIngestService(),  # type: ignore[arg-type]
            user_context=UserContext(telegram_user_id="100500", linked=True, user_id="user-1"),
            telegram_user_id="100500",
        )

        assert events == [
            ("reply", "Загружаю и сохраняю…"),
            ("download", "too-large-file"),
            ("edit", DOWNLOAD_FAILED),
        ]

    asyncio.run(scenario())


def test_download_error_text_detects_too_large_file() -> None:
    assert _download_error_text(RuntimeError("Bad Request: file is too big")) == FILE_TOO_LARGE
