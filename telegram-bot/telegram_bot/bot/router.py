from __future__ import annotations

from aiogram import Router

from telegram_bot.handlers import help, ingest, modes, start, unknown


def build_router() -> Router:
    router = Router(name="telegram_bot")
    for child in (
        start.router,
        help.router,
        modes.router,
        unknown.router,
        ingest.router,
    ):
        child._parent_router = None
        router.include_router(child)
    return router
