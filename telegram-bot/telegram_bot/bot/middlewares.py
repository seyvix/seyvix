from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from telegram_bot.domain.models import UserContext
from telegram_bot.infrastructure.backend_client import (
    BackendError,
    BackendUnavailableError,
    HttpSeyvixBackend,
)
from telegram_bot.texts.common import BACKEND_UNAVAILABLE, access_denied

logger = logging.getLogger(__name__)


class UserStatusCache:
    """Short-lived per-user access status, so a burst of messages costs one backend call."""

    def __init__(
        self,
        backend: HttpSeyvixBackend,
        *,
        ttl_seconds: float,
        max_entries: int = 10_000,
    ) -> None:
        self.backend = backend
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[int, tuple[float, UserContext]] = OrderedDict()
        self._inflight: dict[int, asyncio.Task[UserContext]] = {}

    async def get(self, telegram_user_id: int, username: str | None) -> UserContext:
        cached = self._entries.get(telegram_user_id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        task = self._inflight.get(telegram_user_id)
        if task is None:
            task = asyncio.create_task(self._load(telegram_user_id, username))
            self._inflight[telegram_user_id] = task
            task.add_done_callback(lambda _: self._inflight.pop(telegram_user_id, None))
        return await asyncio.shield(task)

    def invalidate(self, telegram_user_id: int | None = None) -> None:
        if telegram_user_id is None:
            self._entries.clear()
        else:
            self._entries.pop(telegram_user_id, None)

    async def _load(self, telegram_user_id: int, username: str | None) -> UserContext:
        context = await self.backend.user_status(
            telegram_user_id=telegram_user_id,
            username=username,
        )
        self._entries[telegram_user_id] = (time.monotonic() + self.ttl_seconds, context)
        self._entries.move_to_end(telegram_user_id)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return context


class AccessMiddleware(BaseMiddleware):
    """Lets only allowed users through; injects `user: UserContext` for handlers."""

    def __init__(self, cache: UserStatusCache) -> None:
        self.cache = cache

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        sender = _sender(event)
        if sender is None or sender.is_bot:
            return None
        try:
            context = await self.cache.get(sender.id, sender.username)
        except (BackendUnavailableError, BackendError) as exc:
            logger.warning("User status unavailable: %s", exc)
            await _reply(event, BACKEND_UNAVAILABLE)
            return None
        if not context.allowed:
            await _reply(event, access_denied(sender.id))
            return None
        data["user"] = context
        return await handler(event, data)


def _sender(event: TelegramObject) -> User | None:
    if isinstance(event, Message | CallbackQuery):
        return event.from_user
    return None


async def _reply(event: TelegramObject, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer()
        if isinstance(event.message, Message):
            await event.message.answer(text)
