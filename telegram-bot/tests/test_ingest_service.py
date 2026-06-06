from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import (
    BotState,
    InboundMaterial,
    MaterialType,
    SavedMaterial,
    SourceMetadata,
)
from telegram_bot.services.ingest import TelegramIngestService


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def ingest(
        self,
        material: InboundMaterial,
        *,
        target_collection_id: str | None = None,
    ) -> dict[str, object]:
        self.calls.append((material.telegram_message_id, target_collection_id))
        note_id = f"saved-{len(self.calls)}"
        return {
            "status": "collection_updated" if target_collection_id else "saved",
            "note": {"id": note_id, "title": note_id},
        }


class FakeStateRepository:
    async def save(self, state: BotState) -> BotState:
        return state


def _state(mode: BotMode) -> BotState:
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    return BotState(
        telegram_user_id="100500",
        mode=mode,
        created_at=now,
        updated_at=now,
    )


def _material(message_id: str, *, group_id: str | None = None) -> InboundMaterial:
    return InboundMaterial(
        telegram_user_id="100500",
        telegram_chat_id="700",
        telegram_message_id=message_id,
        message_date=1_777_777_777,
        material_type=MaterialType.PHOTO if group_id else MaterialType.TEXT,
        text=None if group_id else f"text-{message_id}",
        caption=None,
        attachment=None,
        source=SourceMetadata(
            provider="telegram",
            provider_label="Telegram",
            external_id=f"700:{message_id}",
            group_id=group_id,
        ),
    )


def test_auto_mode_keeps_media_group_and_nearby_text_in_one_bucket() -> None:
    async def scenario() -> None:
        backend = FakeBackend()
        saved_statuses: list[tuple[str, str]] = []
        service = TelegramIngestService(
            backend=backend,  # type: ignore[arg-type]
            state_repository=FakeStateRepository(),  # type: ignore[arg-type]
            auto_group_window_seconds=0.01,
            media_group_flush_seconds=0.01,
        )

        async def update_saved(status: str, saved: SavedMaterial) -> None:
            saved_statuses.append((status, saved.id or ""))

        async def update_error(status: str, exc: Exception) -> None:
            raise AssertionError(f"{status}: {exc}")

        await service.ingest(
            material=_material("10", group_id="album-1"),
            state=_state(BotMode.AUTO),
            status="status-1",
            update_saved=update_saved,
            update_error=update_error,
        )
        await service.ingest(
            material=_material("11"),
            state=_state(BotMode.AUTO),
            status="status-2",
            update_saved=update_saved,
            update_error=update_error,
        )
        await asyncio.sleep(0.03)

        assert backend.calls == [("10", None), ("11", "saved-1")]
        assert saved_statuses == [("status-1", "saved-2"), ("status-2", "saved-2")]

    asyncio.run(scenario())
