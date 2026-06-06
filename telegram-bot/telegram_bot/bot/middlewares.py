from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend

logger = logging.getLogger(__name__)


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, backend: HttpSeyvixBackend) -> None:
        self.backend = backend

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user_id = _telegram_user_id(event)
        data["telegram_user_id"] = telegram_user_id
        if telegram_user_id is not None:
            try:
                data["user_context"] = await self.backend.status(
                    telegram_user_id=telegram_user_id,
                )
                logger.debug(
                    "Telegram user context loaded telegram_user_id=%s linked=%s",
                    telegram_user_id,
                    data["user_context"].linked,
                )
            except Exception:
                logger.exception(
                    "Failed to load Telegram user context telegram_user_id=%s",
                    telegram_user_id,
                )
                data["user_context"] = None
        return await handler(event, data)


def _telegram_user_id(event: TelegramObject) -> str | None:
    user = None
    if isinstance(event, Message):
        user = event.from_user
    elif isinstance(event, CallbackQuery):
        user = event.from_user
    if user is None:
        return None
    return str(user.id)
