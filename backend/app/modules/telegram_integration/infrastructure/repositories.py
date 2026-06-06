from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User


class TelegramIngestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_telegram_id(self, telegram_user_id: str) -> User | None:
        query = select(User).where(User.telegram_id == telegram_user_id)
        return cast(User | None, await self.session.scalar(query))
