from __future__ import annotations

from functools import cache

from aiogram import Router

from telegram_bot.handlers import admin, help, ingest, modes, start, unknown


@cache
def build_router() -> Router:
    """Root router; aiogram routers can be attached once, so it is built once per process."""
    router = Router(name="telegram_bot")
    # Order matters: commands first, the catch-all ingest handler last.
    router.include_routers(
        start.router,
        help.router,
        modes.router,
        admin.router,
        unknown.router,
        ingest.router,
    )
    return router
