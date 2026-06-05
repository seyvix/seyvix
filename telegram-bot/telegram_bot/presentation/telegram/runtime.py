from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo

from telegram_bot.application.use_cases import BotUseCases
from telegram_bot.presentation.telegram.factory import build_dispatcher


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
    use_cases: BotUseCases,
    web_app_url: str | None,
    media_group_flush_seconds: float,
) -> None:
    dispatcher = build_dispatcher(
        use_cases=use_cases,
        web_app_url=web_app_url,
        media_group_flush_seconds=media_group_flush_seconds,
    )
    await configure_web_app_menu_button(bot, web_app_url)
    await dispatcher.start_polling(bot)
