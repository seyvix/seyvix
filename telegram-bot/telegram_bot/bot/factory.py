from __future__ import annotations

from aiogram import Dispatcher

from telegram_bot.bot.middlewares import UserContextMiddleware
from telegram_bot.bot.router import build_router
from telegram_bot.config import AUTO_GROUP_WINDOW_SECONDS
from telegram_bot.infrastructure.backend_client import HttpSeyvixBackend
from telegram_bot.infrastructure.memory_state_repository import MemoryBotStateRepository
from telegram_bot.services.ingest import TelegramIngestService
from telegram_bot.services.modes import ModeService
from telegram_bot.services.state import BotStateRepository


def build_dispatcher(
    *,
    backend: HttpSeyvixBackend,
    web_app_url: str | None,
    state_repository: BotStateRepository | None = None,
    media_group_flush_seconds: float = 1.2,
) -> Dispatcher:
    state_repository = state_repository or MemoryBotStateRepository()
    mode_service = ModeService(state_repository)
    ingest_service = TelegramIngestService(
        backend=backend,
        state_repository=state_repository,
        auto_group_window_seconds=AUTO_GROUP_WINDOW_SECONDS,
        media_group_flush_seconds=media_group_flush_seconds,
    )
    dispatcher = Dispatcher()
    user_context_middleware = UserContextMiddleware(backend)
    dispatcher.message.middleware(user_context_middleware)
    dispatcher.callback_query.middleware(user_context_middleware)
    dispatcher.include_router(build_router())
    dispatcher["backend"] = backend
    dispatcher["web_app_url"] = web_app_url
    dispatcher["state_repository"] = state_repository
    dispatcher["mode_service"] = mode_service
    dispatcher["ingest_service"] = ingest_service
    return dispatcher
