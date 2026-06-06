from __future__ import annotations

from datetime import UTC, datetime

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState


class MemoryBotStateRepository:
    def __init__(self) -> None:
        self.states: dict[str, BotState] = {}

    async def get_or_create(self, telegram_user_id: str) -> BotState:
        state = self.states.get(telegram_user_id)
        if state is not None:
            return state
        now = datetime.now(UTC)
        state = BotState(
            telegram_user_id=telegram_user_id,
            mode=BotMode.AUTO,
            created_at=now,
            updated_at=now,
        )
        self.states[telegram_user_id] = state
        return state

    async def save(self, state: BotState) -> BotState:
        self.states[state.telegram_user_id] = state
        return state

    async def list_manual_collections(self) -> list[BotState]:
        return [
            state
            for state in self.states.values()
            if state.mode == BotMode.MANUAL_COLLECTION and state.active_collection_id is not None
        ]
