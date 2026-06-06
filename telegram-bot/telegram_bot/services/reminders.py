from __future__ import annotations

from datetime import datetime, timedelta

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState
from telegram_bot.services.state import BotStateRepository


class ManualCollectionReminderService:
    def __init__(
        self,
        repository: BotStateRepository,
        *,
        reminder_delay_seconds: int,
    ) -> None:
        self.repository = repository
        self.reminder_delay = timedelta(seconds=reminder_delay_seconds)

    async def due_states(self, *, now: datetime) -> list[BotState]:
        states = await self.repository.list_manual_collections()
        return [
            state
            for state in states
            if state.mode == BotMode.MANUAL_COLLECTION
            and state.active_collection_id is not None
            and state.manual_collection_started_at is not None
            and state.manual_collection_reminder_sent_at is None
            and now - state.manual_collection_started_at >= self.reminder_delay
        ]

    async def mark_sent(self, state: BotState, *, now: datetime) -> BotState:
        return await self.repository.save(state.mark_manual_collection_reminder_sent(now=now))
