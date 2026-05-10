from __future__ import annotations

from aiogram import Dispatcher

from telegram_bot.application.use_cases import BotUseCases
from telegram_bot.presentation.telegram.router import build_router


def build_dispatcher(*, use_cases: BotUseCases, web_app_url: str | None) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    dispatcher["use_cases"] = use_cases
    dispatcher["web_app_url"] = web_app_url
    return dispatcher
