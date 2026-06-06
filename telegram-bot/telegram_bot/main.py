from __future__ import annotations

import asyncio
import logging

import httpx

from telegram_bot.bot.runtime import build_bot, run_polling
from telegram_bot.config import get_settings
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.infrastructure.state_repository import (
    PostgresBotStateRepository,
    create_state_pool,
)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    state_pool = await create_state_pool(settings.telegram_bot_database_url)
    state_repository = PostgresBotStateRepository(state_pool)
    await state_repository.ensure_schema()
    async with httpx.AsyncClient(timeout=60) as client:
        backend = HttpSeyvixBackend(
            client=client,
            base_url=settings.telegram_backend_base_url,
            internal_token=settings.telegram_internal_token,
        )
        try:
            await run_polling(
                bot=build_bot(settings.telegram_bot_token, settings.telegram_api_base),
                backend=backend,
                web_app_url=settings.telegram_web_app_url,
                state_repository=state_repository,
                media_group_flush_seconds=settings.telegram_media_group_flush_seconds,
            )
        finally:
            await state_pool.close()


if __name__ == "__main__":
    asyncio.run(main())
