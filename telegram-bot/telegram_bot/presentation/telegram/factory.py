from __future__ import annotations

from aiogram import Dispatcher
from telegram_bot.application.use_cases import BotUseCases
from telegram_bot.presentation.telegram.media_group_buffer import MediaGroupBuffer
from telegram_bot.presentation.telegram.router import build_router


def build_dispatcher(
    *,
    use_cases: BotUseCases,
    web_app_url: str | None,
    media_group_flush_seconds: float = 1.2,
) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    dispatcher["use_cases"] = use_cases
    dispatcher["web_app_url"] = web_app_url
    dispatcher["media_group_buffer"] = MediaGroupBuffer(
        flush_delay_seconds=media_group_flush_seconds,
    )
    return dispatcher
