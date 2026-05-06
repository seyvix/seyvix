from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PollingWorker(Protocol):
    async def run_once(self, *, limit: int) -> int: ...


async def poll_worker_forever(
    session_factory: async_sessionmaker[AsyncSession],
    worker_factory: Callable[[AsyncSession], PollingWorker],
    *,
    limit: int,
    idle_sleep_seconds: float,
) -> None:
    while True:
        async with session_factory() as session:
            processed = await worker_factory(session).run_once(limit=limit)
        if processed == 0:
            await asyncio.sleep(idle_sleep_seconds)
