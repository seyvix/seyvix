from __future__ import annotations

from typing import cast

from app.modules.auth.models import User
from app.modules.telegram_integration.models import TelegramIngestState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class TelegramIngestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_telegram_id(self, telegram_user_id: str) -> User | None:
        query = select(User).where(User.telegram_id == telegram_user_id)
        return cast(User | None, await self.session.scalar(query))

    async def get_or_create_state(self, owner_user_id: str) -> TelegramIngestState:
        state = cast(
            TelegramIngestState | None,
            await self.session.scalar(
                select(TelegramIngestState).where(
                    TelegramIngestState.owner_user_id == owner_user_id
                )
            ),
        )
        if state is not None:
            return state

        state = TelegramIngestState(owner_user_id=owner_user_id)
        self.session.add(state)
        await self.session.flush()
        return state
