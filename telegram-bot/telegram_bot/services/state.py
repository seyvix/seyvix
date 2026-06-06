from __future__ import annotations

from typing import Protocol

from telegram_bot.domain.models import BotState


class BotStateRepository(Protocol):
    async def get_or_create(self, telegram_user_id: str) -> BotState: ...

    async def save(self, state: BotState) -> BotState: ...

    async def list_manual_collections(self) -> list[BotState]: ...
