from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo

from telegram_bot.bot.commands import configure_bot_commands
from telegram_bot.bot.factory import build_dispatcher
from telegram_bot.config import MANUAL_COLLECTION_REMINDER_SECONDS
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.services.reminders import ManualCollectionReminderService
from telegram_bot.services.state import BotStateRepository
from telegram_bot.texts.modes import MANUAL_COLLECTION_REMINDER


def build_bot(token: str, telegram_api_base: str | None = None) -> Bot:
    session = None
    if telegram_api_base is not None:
        session = AiohttpSession(api=TelegramAPIServer.from_base(telegram_api_base))
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def configure_web_app_menu_button(bot: Bot, web_app_url: str | None) -> None:
    if not web_app_url:
        return
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Seyvix",
            web_app=WebAppInfo(url=web_app_url),
        )
    )


async def run_polling(
    *,
    bot: Bot,
    backend: HttpSeyvixBackend,
    web_app_url: str | None,
    state_repository: BotStateRepository,
    media_group_flush_seconds: float,
) -> None:
    dispatcher = build_dispatcher(
        backend=backend,
        web_app_url=web_app_url,
        state_repository=state_repository,
        media_group_flush_seconds=media_group_flush_seconds,
    )
    await configure_web_app_menu_button(bot, web_app_url)
    await configure_bot_commands(bot)
    reminder_task = asyncio.create_task(_run_manual_collection_reminders(bot, state_repository))
    try:
        await dispatcher.start_polling(bot)
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass


async def _run_manual_collection_reminders(
    bot: Bot,
    state_repository: BotStateRepository,
) -> None:
    service = ManualCollectionReminderService(
        state_repository,
        reminder_delay_seconds=MANUAL_COLLECTION_REMINDER_SECONDS,
    )
    while True:
        await asyncio.sleep(60)
        for state in await service.due_states(now=datetime.now(UTC)):
            await bot.send_message(
                chat_id=state.telegram_user_id,
                text=MANUAL_COLLECTION_REMINDER,
            )
            await service.mark_sent(state, now=datetime.now(UTC))
