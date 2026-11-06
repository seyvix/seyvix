from __future__ import annotations

import asyncio
import logging

import httpx

from telegram_bot.bot.runtime import run_bot
from telegram_bot.config import get_settings
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # Uploads of up to 20 files can take a while; connecting must be quick to detect outages.
    timeout = httpx.Timeout(120.0, connect=5.0)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        backend = HttpSeyvixBackend(
            client=client,
            base_url=settings.backend_url,
            internal_token=settings.telegram_internal_token,
        )
        await run_bot(settings, backend)


if __name__ == "__main__":
    asyncio.run(main())
