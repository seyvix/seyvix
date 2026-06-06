from __future__ import annotations

from aiogram import Router

from telegram_bot.handlers import app, help, ingest, modes, settings, start, unknown


def build_router() -> Router:
    router = Router(name="telegram_bot")
    for child in (
        start.router,
        help.router,
        app.router,
        settings.router,
        modes.router,
        unknown.router,
        ingest.router,
    ):
        child._parent_router = None
        router.include_router(child)
    return router
