"""Bot state persistence (`telegram_bot_states`). Every operation is a single atomic statement so
concurrent bot handlers (e.g. /finish racing an ingest flush) never lose updates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telegram_integration.models import (
    BOT_MODE_AUTO,
    BOT_MODE_MANUAL_COLLECTION,
    TelegramBotState,
)
from app.modules.telegram_integration.schemas import BotStateResponse

_CLEARED_COLLECTION: dict[str, Any] = {
    "active_collection_id": None,
    "manual_collection_started_at": None,
    "manual_collection_last_item_at": None,
    "manual_collection_reminder_sent_at": None,
}


def state_response(state: TelegramBotState) -> BotStateResponse:
    return BotStateResponse(
        telegram_user_id=state.telegram_user_id,
        mode=cast(Any, state.mode),
        active_collection_id=state.active_collection_id,
        manual_collection_started_at=state.manual_collection_started_at,
    )


class BotStateStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, telegram_user_id: int) -> TelegramBotState:
        await self.session.execute(
            insert(TelegramBotState)
            .values(telegram_user_id=telegram_user_id, mode=BOT_MODE_AUTO)
            .on_conflict_do_nothing(index_elements=[TelegramBotState.telegram_user_id])
        )
        state = await self.session.scalar(
            select(TelegramBotState)
            .where(TelegramBotState.telegram_user_id == telegram_user_id)
            .execution_options(populate_existing=True)
        )
        return cast(TelegramBotState, state)

    async def set_mode(self, telegram_user_id: int, mode: str) -> TelegramBotState:
        now = datetime.now(UTC)
        values: dict[str, Any] = {"mode": mode, "updated_at": now}
        if mode != BOT_MODE_MANUAL_COLLECTION:
            values.update(_CLEARED_COLLECTION)
        statement = (
            insert(TelegramBotState)
            .values(telegram_user_id=telegram_user_id, created_at=now, **values)
            .on_conflict_do_update(index_elements=[TelegramBotState.telegram_user_id], set_=values)
            .returning(TelegramBotState)
            .execution_options(populate_existing=True)
        )
        return cast(TelegramBotState, await self.session.scalar(statement))

    async def finish_collection(self, telegram_user_id: int) -> tuple[bool, TelegramBotState]:
        """Close the manual collection and return to auto mode; (had_collection, state)."""
        state = await self.session.scalar(
            select(TelegramBotState)
            .where(TelegramBotState.telegram_user_id == telegram_user_id)
            .with_for_update()
        )
        if state is None:
            return False, await self.get_or_create(telegram_user_id)
        had_collection = state.active_collection_id is not None
        state.mode = BOT_MODE_AUTO
        for key, value in _CLEARED_COLLECTION.items():
            setattr(state, key, value)
        await self.session.flush()
        return had_collection, state

    async def record_collection_item(
        self,
        telegram_user_id: int,
        *,
        expected_collection_id: str | None,
        collection_id: str,
    ) -> None:
        """Point the manual collection at `collection_id` unless the user changed mode or
        finished the collection while the items were being saved."""
        now = datetime.now(UTC)
        await self.session.execute(
            update(TelegramBotState)
            .where(
                TelegramBotState.telegram_user_id == telegram_user_id,
                TelegramBotState.mode == BOT_MODE_MANUAL_COLLECTION,
                TelegramBotState.active_collection_id.is_not_distinct_from(expected_collection_id),
            )
            .values(
                active_collection_id=collection_id,
                manual_collection_started_at=(
                    now
                    if expected_collection_id != collection_id
                    else TelegramBotState.manual_collection_started_at
                ),
                manual_collection_last_item_at=now,
                manual_collection_reminder_sent_at=None,
                updated_at=now,
            )
        )

    async def claim_due_reminders(self, *, idle_seconds: int) -> list[int]:
        """Mark collections idle for `idle_seconds` as reminded and return their users."""
        now = datetime.now(UTC)
        result = await self.session.scalars(
            update(TelegramBotState)
            .where(
                TelegramBotState.mode == BOT_MODE_MANUAL_COLLECTION,
                TelegramBotState.active_collection_id.is_not(None),
                TelegramBotState.manual_collection_reminder_sent_at.is_(None),
                TelegramBotState.manual_collection_last_item_at
                <= now - timedelta(seconds=idle_seconds),
            )
            .values(manual_collection_reminder_sent_at=now)
            .returning(TelegramBotState.telegram_user_id)
        )
        return list(result)
