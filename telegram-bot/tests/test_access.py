from __future__ import annotations

import asyncio

from telegram_bot.bot.middlewares import UserStatusCache
from telegram_bot.domain.models import UserContext
from telegram_bot.handlers.admin import parse_target
from telegram_bot.texts.common import access_denied


class CountingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def user_status(self, *, telegram_user_id: int, username: str | None) -> UserContext:
        self.calls += 1
        await asyncio.sleep(0.01)
        return UserContext(
            telegram_user_id=telegram_user_id, allowed=True, is_admin=False, linked=True
        )


def test_status_cache_dedupes_bursts_and_expires_on_invalidate() -> None:
    backend = CountingBackend()

    async def scenario() -> None:
        cache = UserStatusCache(backend, ttl_seconds=60)  # type: ignore[arg-type]
        results = await asyncio.gather(*(cache.get(1, None) for _ in range(10)))
        assert all(result.allowed for result in results)
        await cache.get(1, None)
        assert backend.calls == 1
        cache.invalidate(1)
        await cache.get(1, None)
        assert backend.calls == 2

    asyncio.run(scenario())


def test_parse_target_accepts_ids_and_usernames() -> None:
    assert parse_target("123") == (123, None)
    assert parse_target("@Some_User") == (None, "some_user")
    assert parse_target("plainname") == (None, "plainname")
    assert parse_target("0") is None
    assert parse_target("bad name!") is None
    assert parse_target("@x") is None


def test_access_denied_text_shows_telegram_id() -> None:
    assert "<code>987</code>" in access_denied(987)
