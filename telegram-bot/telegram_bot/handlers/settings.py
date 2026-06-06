from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from telegram_bot.domain.models import UserContext
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.services.modes import ModeService
from telegram_bot.texts.common import AUTH_REQUIRED
from telegram_bot.texts.modes import settings_text

router = Router(name="settings")


@router.message(Command("settings"))
async def settings_handler(
    message: Message,
    mode_service: ModeService,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
    telegram_user_id: str | None = None,
) -> None:
    if user_context is None or not user_context.linked or telegram_user_id is None:
        await message.answer(AUTH_REQUIRED, reply_markup=web_app_keyboard(web_app_url))
        return

    state = await mode_service.get_state(telegram_user_id)
    await message.answer(settings_text(state.mode), reply_markup=web_app_keyboard(web_app_url))
