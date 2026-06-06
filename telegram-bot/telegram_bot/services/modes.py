from __future__ import annotations

from datetime import UTC, datetime

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState
from telegram_bot.services.state import BotStateRepository


class ModeService:
    def __init__(self, repository: BotStateRepository) -> None:
        self.repository = repository

    async def get_state(self, telegram_user_id: str) -> BotState:
        return await self.repository.get_or_create(telegram_user_id)

    async def set_mode(self, telegram_user_id: str, mode: BotMode) -> BotState:
        state = await self.repository.get_or_create(telegram_user_id)
        return await self.repository.save(state.with_mode(mode, now=datetime.now(UTC)))

    async def finish_collection(self, telegram_user_id: str) -> BotState:
        state = await self.repository.get_or_create(telegram_user_id)
        return await self.repository.save(state.finish_collection(now=datetime.now(UTC)))
