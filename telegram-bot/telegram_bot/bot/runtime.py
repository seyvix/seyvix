from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from telegram_bot.bot.commands import configure_bot
from telegram_bot.bot.factory import build_dispatcher
from telegram_bot.bot.middlewares import UserStatusCache
from telegram_bot.config import (
    MANUAL_COLLECTION_REMINDER_IDLE_SECONDS,
    MAX_BUFFERED_MATERIALS,
    MEDIA_GROUP_FLUSH_SECONDS,
    REMINDER_POLL_SECONDS,
    TELEGRAM_MAX_DOWNLOAD_BYTES,
    USER_STATUS_CACHE_SECONDS,
    Settings,
)
from telegram_bot.infrastructure.backend_client import (
    BackendError,
    BackendUnavailableError,
    HttpSeyvixBackend,
)
from telegram_bot.infrastructure.telegram_files import TelegramFileFetcher
from telegram_bot.services.ingest import TelegramIngestService
from telegram_bot.texts.modes import MANUAL_COLLECTION_REMINDER

logger = logging.getLogger(__name__)

STARTUP_CONFIG_ATTEMPTS = 5


def build_bot(token: str, telegram_api_base: str | None = None) -> Bot:
    session = (
        AiohttpSession(api=TelegramAPIServer.from_base(telegram_api_base))
        if telegram_api_base
        else None
    )
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run_bot(settings: Settings, backend: HttpSeyvixBackend) -> None:
    bot = build_bot(settings.telegram_bot_token, settings.telegram_api_base)
    ingest_service = TelegramIngestService(
        backend=backend,
        fetcher=TelegramFileFetcher(bot),
        group_window_seconds=settings.group_window_seconds,
        media_group_seconds=MEDIA_GROUP_FLUSH_SECONDS,
        max_buffered_materials=MAX_BUFFERED_MATERIALS,
        # A self-hosted Bot API server (TELEGRAM_API_BASE) has no 20 MB download limit.
        max_download_bytes=None if settings.telegram_api_base else TELEGRAM_MAX_DOWNLOAD_BYTES,
    )
    dispatcher = build_dispatcher(
        backend=backend,
        ingest_service=ingest_service,
        status_cache=UserStatusCache(backend, ttl_seconds=USER_STATUS_CACHE_SECONDS),
        web_app_url=settings.web_app_url,
    )
    background = [
        asyncio.create_task(_configure_with_retry(bot, settings.web_app_url)),
        asyncio.create_task(_run_reminders(bot, backend)),
    ]
    try:
        # aiogram retries getUpdates with backoff on network errors and stops on SIGINT/SIGTERM.
        await dispatcher.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await ingest_service.shutdown()
        await bot.session.close()


async def _configure_with_retry(bot: Bot, web_app_url: str | None) -> None:
    """Commands/menu button are cosmetic: retry with backoff, never crash the bot."""
    for attempt in range(1, STARTUP_CONFIG_ATTEMPTS + 1):
        try:
            await configure_bot(bot, web_app_url=web_app_url)
            return
        except TelegramAPIError as exc:
            delay = min(60, 2**attempt)
            logger.warning("Bot configuration failed (%s); retry in %ss", exc, delay)
            await asyncio.sleep(delay)
    logger.error("Giving up configuring bot commands/menu button")


async def _run_reminders(bot: Bot, backend: HttpSeyvixBackend) -> None:
    while True:
        await asyncio.sleep(REMINDER_POLL_SECONDS)
        try:
            user_ids = await backend.claim_reminders(
                idle_seconds=MANUAL_COLLECTION_REMINDER_IDLE_SECONDS,
            )
        except (BackendUnavailableError, BackendError) as exc:
            logger.warning("Could not claim collection reminders: %s", exc)
            continue
        for user_id in user_ids:
            try:
                await bot.send_message(chat_id=user_id, text=MANUAL_COLLECTION_REMINDER)
            except TelegramForbiddenError:
                logger.info("User blocked the bot; reminder skipped")
            except TelegramAPIError:
                logger.warning("Could not send collection reminder", exc_info=True)
