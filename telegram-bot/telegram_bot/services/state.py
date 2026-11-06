from __future__ import annotations

import time
from collections import OrderedDict

from telegram_bot.domain.enums import BotMode
from telegram_bot.domain.models import BotState
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend


class BotStateService:
    """Bot state lives in the backend; the saving mode is cached because every incoming
    message needs it (only this bot changes it, so the cache is updated on every change)."""

    def __init__(
        self,
        backend: HttpSeyvixBackend,
        *,
        ttl_seconds: float = 600.0,
        max_entries: int = 10_000,
    ) -> None:
        self.backend = backend
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._modes: OrderedDict[int, tuple[float, BotMode]] = OrderedDict()

    async def get_state(self, telegram_user_id: int) -> BotState:
        return self._remember(await self.backend.get_state(telegram_user_id))

    async def get_mode(self, telegram_user_id: int) -> BotMode:
        cached = self._modes.get(telegram_user_id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        return (await self.get_state(telegram_user_id)).mode

    async def set_mode(self, telegram_user_id: int, mode: BotMode) -> BotState:
        return self._remember(await self.backend.set_mode(telegram_user_id, mode))

    async def finish_collection(self, telegram_user_id: int) -> tuple[bool, BotState]:
        finished, state = await self.backend.finish_collection(telegram_user_id)
        self._remember(state)
        return finished, state

    def _remember(self, state: BotState) -> BotState:
        self._modes[state.telegram_user_id] = (time.monotonic() + self.ttl_seconds, state.mode)
        self._modes.move_to_end(state.telegram_user_id)
        while len(self._modes) > self.max_entries:
            self._modes.popitem(last=False)
        return state
