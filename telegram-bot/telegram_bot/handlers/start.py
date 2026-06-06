from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from telegram_bot.domain.models import UserContext
from telegram_bot.keyboards.common import web_app_keyboard
from telegram_bot.texts.start import START_LINKED, START_UNLINKED

router = Router(name="start")


@router.message(CommandStart())
async def start_handler(
    message: Message,
    user_context: UserContext | None = None,
    web_app_url: str | None = None,
) -> None:
    text = START_LINKED if user_context is not None and user_context.linked else START_UNLINKED
    await message.answer(text, reply_markup=web_app_keyboard(web_app_url))
