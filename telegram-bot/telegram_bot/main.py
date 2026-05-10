from __future__ import annotations

import asyncio
import logging

import httpx

from telegram_bot.application.use_cases import BotUseCases
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.infrastructure.settings import get_settings
from telegram_bot.presentation.telegram.runtime import build_bot, run_polling


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    async with httpx.AsyncClient(timeout=60) as client:
        backend = HttpSeyvixBackend(
            client=client,
            base_url=settings.telegram_backend_base_url,
            internal_token=settings.telegram_internal_token,
        )
        await run_polling(
            bot=build_bot(settings.telegram_bot_token),
            use_cases=BotUseCases(backend=backend),
            web_app_url=settings.telegram_web_app_url,
        )


if __name__ == "__main__":
    asyncio.run(main())
