from __future__ import annotations

from aiogram import Dispatcher

from telegram_bot.bot.middlewares import AccessMiddleware, UserStatusCache
from telegram_bot.bot.router import build_router
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.services.ingest import TelegramIngestService
from telegram_bot.services.state import BotStateService


def build_dispatcher(
    *,
    backend: HttpSeyvixBackend,
    ingest_service: TelegramIngestService,
    status_cache: UserStatusCache,
    web_app_url: str | None,
) -> Dispatcher:
    dispatcher = Dispatcher()
    access = AccessMiddleware(status_cache)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    dispatcher.include_router(build_router())
    dispatcher["backend"] = backend
    dispatcher["status_cache"] = status_cache
    dispatcher["state_service"] = BotStateService(backend)
    dispatcher["ingest_service"] = ingest_service
    dispatcher["web_app_url"] = web_app_url
    return dispatcher
